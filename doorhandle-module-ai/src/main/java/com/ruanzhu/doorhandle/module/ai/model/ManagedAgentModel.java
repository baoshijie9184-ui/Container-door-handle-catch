package com.ruanzhu.doorhandle.module.ai.model;

import com.ruanzhu.doorhandle.module.ai.config.AgentModelProperties;
import io.agentscope.core.message.*;
import io.agentscope.core.model.*;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicLong;
import reactor.core.publisher.SignalType;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/** 多级备用只重发尚未输出内容的模型请求，不重跑 Agent 或工具。 */
final class ManagedAgentModel implements Model {
    private static final Logger log = LoggerFactory.getLogger(ManagedAgentModel.class);
    record Candidate(String id, String provider, Model model, ModelCircuit circuit) {
        Candidate(String id, Model model, ModelCircuit circuit) { this(id, "unknown", model, circuit); }
    }
    private final List<Candidate> candidates;
    private final GenerateOptions policy;
    private final Duration firstTokenTimeout;
    private final Duration timeout;
    private final boolean circuitEnabled;
    ManagedAgentModel(String id, Model primary, Model fallback) {
        this(id, primary, fallback, null);
    }
    ManagedAgentModel(String id, Model primary, Model fallback, GenerateOptions policy) {
        this(legacyCandidates(id, primary, fallback), policy, new AgentModelProperties(), fallback != null);
    }
    ManagedAgentModel(List<Candidate> candidates, GenerateOptions policy, AgentModelProperties settings, boolean circuitEnabled) {
        this.candidates = List.copyOf(candidates); this.policy = policy;
        this.firstTokenTimeout = settings.getFirstTokenTimeout(); this.timeout = settings.getTimeout();
        this.circuitEnabled = circuitEnabled;
    }
    private static List<Candidate> legacyCandidates(String id, Model primary, Model fallback) {
        var result = new ArrayList<Candidate>();
        result.add(new Candidate(id, primary, new ModelCircuit(2, Duration.ofSeconds(60), Duration.ofMinutes(5))));
        if (fallback != null) result.add(new Candidate("fallback", fallback, new ModelCircuit(2, Duration.ofSeconds(60), Duration.ofMinutes(5))));
        return result;
    }
    public Flux<ChatResponse> stream(List<Msg> messages, List<ToolSchema> tools, GenerateOptions options) {
        GenerateOptions enforced = policy == null ? options : GenerateOptions.mergeOptions(policy, options);
        return Flux.deferContextual(context -> attempt(0, messages, tools, enforced,
                        context.getOrDefault(ModelAttemptTrace.CONTEXT_KEY, ModelAttemptTrace.NONE),context.getOrDefault(ModelUsageTrace.CONTEXT_KEY,ModelUsageTrace.NONE)))
                .onErrorMap(error -> {
                    if(error instanceof RedisModelCircuit.Unavailable)return error;
                    log.warn("模型路由失败：model={}, reason={}, status={}", candidates.get(0).id(),
                            ModelFailureClassifier.classify(error), ModelFailureClassifier.status(error));
                    return new IllegalStateException("模型调用失败，请稍后重试（" + candidates.get(0).id() + "）");
                });
    }
    private Flux<ChatResponse> attempt(int index, List<Msg> messages, List<ToolSchema> tools, GenerateOptions options, ModelAttemptTrace trace,ModelUsageTrace usageTrace) {
        if (index >= candidates.size()) return Flux.error(new IllegalStateException("暂无可用模型"));
        return Flux.defer(() -> {
            var candidate = candidates.get(index);
            var permit = circuitEnabled ? candidate.circuit().acquire() : new ModelCircuit.Permit(0, false);
            if (permit == null) {
                var skipped = fields(candidate, index); skipped.put("failureReason", "CIRCUIT_OPEN");
                trace.event("MODEL_CANDIDATE_SKIPPED", skipped);
                return attempt(index + 1, messages, tools, options, trace,usageTrace);
            }
            var emitted = new AtomicBoolean();
            var terminal = new AtomicBoolean();
            var firstContentMs = new AtomicLong(-1);
            String usageId=java.util.UUID.randomUUID().toString();
            var reportedUsage=new java.util.concurrent.atomic.AtomicReference<ChatUsage>();
            long started = System.nanoTime();
            // STARTED 写入失败时仍释放恢复探测 permit，不发出供应商请求。
            return Flux.defer(() -> {
                        trace.event("MODEL_ATTEMPT_STARTED", fields(candidate, index));
                        return candidate.model().stream(messages, tools, options).doOnNext(chunk->{if(chunk.getUsage()!=null)reportedUsage.set(chunk.getUsage());});
                    })
                    // 空元数据不算首字；思考内容或工具参数也算输出，禁止中途跨模型拼接。
                    .filter(chunk -> emitted.get() || hasContent(chunk))
                    // 第一段内容之后使用剩余总预算，持续输出也不能无限延长一次请求。
                    .timeout(Mono.delay(firstTokenTimeout), chunk -> Mono.delay(Duration.ofNanos(
                            Math.max(0, timeout.toNanos() - (System.nanoTime() - started)))))
                    .doOnNext(chunk -> {
                        emitted.set(true);
                        firstContentMs.compareAndSet(-1, (System.nanoTime() - started) / 1_000_000);
                    })
                    .switchIfEmpty(Flux.error(new ModelFailureClassifier.EmptyResponseException()))
                    .doOnComplete(() -> {
                        terminal.set(true);
                        trace.event("MODEL_ATTEMPT_COMPLETED", completedFields(candidate, index, started, firstContentMs.get()));
                        usageTrace.record(usageId,usageFields(candidate,index,started,firstContentMs.get(),reportedUsage.get(),"COMPLETED"));
                        if (circuitEnabled) candidate.circuit().success(permit);
                        if (index > 0) log.info("备用模型请求完成：model={}", candidate.id());
                        if (permit.probe()) log.info("模型恢复验证成功：model={}", candidate.id());
                    })
                    .onErrorResume(error -> {
                        if (error instanceof ModelAttemptTrace.RecordingException) return Flux.error(error);
                        var reason = ModelFailureClassifier.classify(error);
                        terminal.set(true);
                        var failed = completedFields(candidate, index, started, firstContentMs.get());
                        failed.put("failureReason", ModelFailureClassifier.reason(error));
                        Integer status = ModelFailureClassifier.status(error);
                        if (status != null && status >= 100 && status <= 599) failed.put("httpStatus", status);
                        trace.event("MODEL_ATTEMPT_ERROR", failed);
                        usageTrace.record(usageId,usageFields(candidate,index,started,firstContentMs.get(),reportedUsage.get(),"FAILED"));
                        if (circuitEnabled && reason != ModelFailureClassifier.Failure.OTHER) candidate.circuit().failure(permit, reason);
                        if (emitted.get() || reason == ModelFailureClassifier.Failure.OTHER || index + 1 >= candidates.size()) return Flux.error(error);
                        log.warn("切换备用模型：from={}, to={}, reason={}, status={}", candidate.id(), candidates.get(index + 1).id(),
                                reason, ModelFailureClassifier.status(error));
                        var selected = fields(candidate, index);
                        selected.put("nextModelId", candidates.get(index + 1).id());
                        selected.put("failureReason", ModelFailureClassifier.reason(error));
                        trace.event("MODEL_FALLBACK_SELECTED", selected);
                        return attempt(index + 1, messages, tools, options, trace,usageTrace);
                    })
                    .doFinally(signal -> {
                        try {
                            if (signal == SignalType.CANCEL && terminal.compareAndSet(false, true)) {
                                trace.event("MODEL_ATTEMPT_CANCELLED", completedFields(candidate, index, started, firstContentMs.get()));
                                usageTrace.record(usageId,usageFields(candidate,index,started,firstContentMs.get(),reportedUsage.get(),"CANCELLED"));
                            }
                        } catch (ModelAttemptTrace.RecordingException ignored) {
                            // 取消终态可能已经入库；取消回调不能重发请求。
                        } finally { if (circuitEnabled) try{candidate.circuit().release(permit);}catch(RedisModelCircuit.Unavailable ignored){log.warn("模型恢复探测释放尚未核对，将等待租约到期");} }
                    });
        });
    }
    private static Map<String, Object> fields(Candidate candidate, int index) {
        var result = new LinkedHashMap<String, Object>();
        result.put("modelId", candidate.id()); result.put("provider", candidate.provider());
        result.put("model", candidate.model().getModelName()); result.put("attempt", index + 1);
        return result;
    }
    private static Map<String,Object> usageFields(Candidate candidate,int index,long started,long first,ChatUsage usage,String status){var data=completedFields(candidate,index,started,first);data.put("status",status);data.put("basis",usage==null?"UNAVAILABLE":"PROVIDER_REPORTED");data.put("inputTokens",usage==null?null:usage.getInputTokens());data.put("outputTokens",usage==null?null:usage.getOutputTokens());data.put("cachedTokens",usage==null?null:usage.getCachedTokens());return data;}
    private static Map<String, Object> completedFields(Candidate candidate, int index, long started, long firstContentMs) {
        var result = fields(candidate, index);
        result.put("durationMs", (System.nanoTime() - started) / 1_000_000);
        if (firstContentMs >= 0) result.put("firstContentMs", firstContentMs);
        return result;
    }
    private static boolean hasContent(ChatResponse response) {
        if (response.getContent() == null) return false;
        return response.getContent().stream().anyMatch(block -> {
            if (block instanceof TextBlock text) return text.getText() != null && !text.getText().isEmpty();
            if (block instanceof ThinkingBlock thinking) return thinking.getThinking() != null && !thinking.getThinking().isEmpty();
            return true;
        });
    }
    public String getModelName() { return candidates.get(0).model().getModelName(); }
    public int getContextWindowSize() { return candidates.stream().mapToInt(c -> c.model().getContextWindowSize()).min().orElse(0); }
    public boolean supportsNativeStructuredOutput() { return candidates.size() == 1 && candidates.get(0).model().supportsNativeStructuredOutput(); }
    public boolean supportsNativeStructuredOutputWithTools() { return candidates.size() == 1 && candidates.get(0).model().supportsNativeStructuredOutputWithTools(); }
}
