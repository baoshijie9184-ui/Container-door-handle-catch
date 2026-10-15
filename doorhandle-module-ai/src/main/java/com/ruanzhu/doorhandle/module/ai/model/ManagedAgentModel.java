package com.ruanzhu.doorhandle.module.ai.model;

import com.ruanzhu.doorhandle.module.ai.config.AgentModelProperties;
import io.agentscope.core.message.*;
import io.agentscope.core.model.*;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.atomic.AtomicBoolean;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/** 多级备用只重发尚未输出内容的模型请求，不重跑 Agent 或工具。 */
final class ManagedAgentModel implements Model {
    private static final Logger log = LoggerFactory.getLogger(ManagedAgentModel.class);
    record Candidate(String id, Model model, ModelCircuit circuit) {}
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
        return Flux.defer(() -> attempt(0, messages, tools, enforced))
                .onErrorMap(error -> {
                    log.warn("模型路由失败：model={}, reason={}, status={}", candidates.get(0).id(),
                            ModelFailureClassifier.classify(error), ModelFailureClassifier.status(error));
                    return new IllegalStateException("模型调用失败，请稍后重试（" + candidates.get(0).id() + "）");
                });
    }
    private Flux<ChatResponse> attempt(int index, List<Msg> messages, List<ToolSchema> tools, GenerateOptions options) {
        if (index >= candidates.size()) return Flux.error(new IllegalStateException("暂无可用模型"));
        return Flux.defer(() -> {
            var candidate = candidates.get(index);
            var permit = circuitEnabled ? candidate.circuit().acquire() : new ModelCircuit.Permit(0, false);
            if (permit == null) return attempt(index + 1, messages, tools, options);
            var emitted = new AtomicBoolean();
            long started = System.nanoTime();
            return Flux.defer(() -> candidate.model().stream(messages, tools, options))
                    // 空元数据不算首字；思考内容或工具参数也算输出，禁止中途跨模型拼接。
                    .filter(chunk -> emitted.get() || hasContent(chunk))
                    // 第一段内容之后使用剩余总预算，持续输出也不能无限延长一次请求。
                    .timeout(Mono.delay(firstTokenTimeout), chunk -> Mono.delay(Duration.ofNanos(
                            Math.max(0, timeout.toNanos() - (System.nanoTime() - started)))))
                    .doOnNext(chunk -> emitted.set(true))
                    .switchIfEmpty(Flux.error(new ModelFailureClassifier.EmptyResponseException()))
                    .doOnComplete(() -> {
                        if (circuitEnabled) candidate.circuit().success(permit);
                        if (index > 0) log.info("备用模型请求完成：model={}", candidate.id());
                        if (permit.probe()) log.info("模型恢复验证成功：model={}", candidate.id());
                    })
                    .onErrorResume(error -> {
                        var reason = ModelFailureClassifier.classify(error);
                        if (circuitEnabled && reason != ModelFailureClassifier.Failure.OTHER) candidate.circuit().failure(permit, reason);
                        if (emitted.get() || reason == ModelFailureClassifier.Failure.OTHER || index + 1 >= candidates.size()) return Flux.error(error);
                        log.warn("切换备用模型：from={}, to={}, reason={}, status={}", candidate.id(), candidates.get(index + 1).id(),
                                reason, ModelFailureClassifier.status(error));
                        return attempt(index + 1, messages, tools, options);
                    })
                    .doFinally(signal -> { if (circuitEnabled) candidate.circuit().release(permit); });
        });
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
