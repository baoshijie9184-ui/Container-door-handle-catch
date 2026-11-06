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
    private final int maxOutputTokens;
    private ModelBudgetService budget;
    ManagedAgentModel budget(ModelBudgetService value){this.budget=value;return this;}
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
        this.maxOutputTokens = settings.getMaxOutputTokens();
    }
    private static List<Candidate> legacyCandidates(String id, Model primary, Model fallback) {
        var result = new ArrayList<Candidate>();
        result.add(new Candidate(id, primary, new ModelCircuit(2, Duration.ofSeconds(60), Duration.ofMinutes(5))));
        if (fallback != null) result.add(new Candidate("fallback", fallback, new ModelCircuit(2, Duration.ofSeconds(60), Duration.ofMinutes(5))));
        return result;
    }
    public Flux<ChatResponse> stream(List<Msg> messages, List<ToolSchema> tools, GenerateOptions options) {
        GenerateOptions enforced = policy == null ? options : GenerateOptions.mergeOptions(policy, options);
        return Flux.deferContextual(context -> {
                    ModelBudgetContext identity=context.getOrDefault(ModelBudgetContext.CONTEXT_KEY,null);
                    if(budget!=null&&identity==null)return Flux.error(new IllegalStateException("缺少服务端模型额度身份"));
                    return attempt(0,messages,tools,enforced,
                            context.getOrDefault(ModelAttemptTrace.CONTEXT_KEY,ModelAttemptTrace.NONE),
                            context.getOrDefault(ModelUsageTrace.CONTEXT_KEY,ModelUsageTrace.NONE),identity,
                            java.util.UUID.randomUUID().toString());
                })
                .onErrorMap(error -> {
                    if(error instanceof RedisModelCircuit.Unavailable||error instanceof ModelBudgetService.Exhausted)return error;
                    log.warn("模型路由失败：model={}, reason={}, status={}", candidates.get(0).id(),
                            ModelFailureClassifier.classify(error), ModelFailureClassifier.status(error));
                    return new IllegalStateException("模型调用失败，请稍后重试（" + candidates.get(0).id() + "）");
                });
    }
    private Flux<ChatResponse> attempt(int index, List<Msg> messages, List<ToolSchema> tools, GenerateOptions options,
                                      ModelAttemptTrace trace,ModelUsageTrace usageTrace,ModelBudgetContext identity,String requestId) {
        if (index >= candidates.size()) return Flux.error(new IllegalStateException("暂无可用模型"));
        return Flux.defer(() -> {
            var candidate = candidates.get(index);
            var permit = circuitEnabled ? candidate.circuit().acquire() : new ModelCircuit.Permit(0, false);
            if (permit == null) {
                var skipped = fields(candidate, index); skipped.put("failureReason", "CIRCUIT_OPEN");
                trace.event("MODEL_CANDIDATE_SKIPPED", skipped);
                return attempt(index + 1, messages, tools, options, trace,usageTrace,identity,requestId);
            }
            var emitted = new AtomicBoolean();
            var terminal = new AtomicBoolean();
            var firstContentMs = new AtomicLong(-1);
            String usageId=java.util.UUID.randomUUID().toString();
            var reportedUsage=new java.util.concurrent.atomic.AtomicReference<ChatUsage>();
            var ticket=new java.util.concurrent.atomic.AtomicReference<ModelBudgetService.Ticket>();
            long started = System.nanoTime();
            // STARTED 写入失败时仍释放恢复探测 permit，不发出供应商请求。
            return Flux.defer(() -> {
                        trace.event("MODEL_ATTEMPT_STARTED", fields(candidate, index));
                        GenerateOptions attemptOptions=options;
                        if(budget!=null) {
                            var plan=ModelTokenReservation.prepare(messages,tools,options,maxOutputTokens,candidate.model());
                            if("openai".equals(candidate.provider()))
                                io.agentscope.extensions.model.openaiofficial.OpenAIResponsesIoBridge.validateBudgetRequest(
                                        messages,tools,plan.options(),candidate.model().getModelName());
                            ticket.set(budget.started(identity,requestId,usageId,candidate.id(),plan.tokens(),plan.basis()));
                            attemptOptions=plan.options();
                            if(terminal.get()) {
                                // Cancellation can race a blocking admission commit. Do not invoke a new provider afterward.
                                budget.finished(ticket.get(),usageFields(candidate,index,started,firstContentMs.get(),null,"CANCELLED"));
                                return Flux.empty();
                            }
                        }
                        return candidate.model().stream(messages, tools, attemptOptions).doOnNext(chunk->{if(chunk.getUsage()!=null)reportedUsage.set(chunk.getUsage());});
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
                        recordUsage(ticket.get(),usageTrace,usageId,usageFields(candidate,index,started,firstContentMs.get(),reportedUsage.get(),"COMPLETED"));
                        trace.event("MODEL_ATTEMPT_COMPLETED", completedFields(candidate, index, started, firstContentMs.get()));
                        if (circuitEnabled) candidate.circuit().success(permit);
                        if (index > 0) log.info("备用模型请求完成：model={}", candidate.id());
                        if (permit.probe()) log.info("模型恢复验证成功：model={}", candidate.id());
                    })
                    .onErrorResume(error -> {
                        if (terminal.get()||error instanceof ModelAttemptTrace.RecordingException) return Flux.error(error);
                        var reason = ModelFailureClassifier.classify(error);
                        terminal.set(true);
                        recordUsage(ticket.get(),usageTrace,usageId,usageFields(candidate,index,started,firstContentMs.get(),reportedUsage.get(),"FAILED"));
                        var failed = completedFields(candidate, index, started, firstContentMs.get());
                        failed.put("failureReason", ModelFailureClassifier.reason(error));
                        Integer status = ModelFailureClassifier.status(error);
                        if (status != null && status >= 100 && status <= 599) failed.put("httpStatus", status);
                        trace.event("MODEL_ATTEMPT_ERROR", failed);
                        if (circuitEnabled && reason != ModelFailureClassifier.Failure.OTHER) candidate.circuit().failure(permit, reason);
                        if (emitted.get() || reason == ModelFailureClassifier.Failure.OTHER || index + 1 >= candidates.size()) return Flux.error(error);
                        log.warn("切换备用模型：from={}, to={}, reason={}, status={}", candidate.id(), candidates.get(index + 1).id(),
                                reason, ModelFailureClassifier.status(error));
                        var selected = fields(candidate, index);
                        selected.put("nextModelId", candidates.get(index + 1).id());
                        selected.put("failureReason", ModelFailureClassifier.reason(error));
                        trace.event("MODEL_FALLBACK_SELECTED", selected);
                        return attempt(index + 1, messages, tools, options, trace,usageTrace,identity,requestId);
                    })
                    .doFinally(signal -> {
                        try {
                            if (signal == SignalType.CANCEL && terminal.compareAndSet(false, true)) {
                                recordUsage(ticket.get(),usageTrace,usageId,usageFields(candidate,index,started,firstContentMs.get(),reportedUsage.get(),"CANCELLED"));
                                trace.event("MODEL_ATTEMPT_CANCELLED", completedFields(candidate, index, started, firstContentMs.get()));
                            }
                        } catch (ModelAttemptTrace.RecordingException ignored) {
                            // 取消终态可能已经入库；取消回调不能重发请求。
                        } finally { if (circuitEnabled) try{candidate.circuit().release(permit);}catch(RedisModelCircuit.Unavailable ignored){log.warn("模型恢复探测释放尚未核对，将等待租约到期");} }
                    });
        });
    }
    private void recordUsage(ModelBudgetService.Ticket ticket,ModelUsageTrace usageTrace,String usageId,Map<String,Object> fields) {
        if(ticket!=null)try { budget.finished(ticket,fields); }
        catch(RuntimeException failure) { throw new ModelAttemptTrace.RecordingException(); }
        usageTrace.record(usageId,fields);
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
