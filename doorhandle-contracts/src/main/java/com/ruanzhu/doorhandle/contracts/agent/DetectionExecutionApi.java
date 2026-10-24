package com.ruanzhu.doorhandle.contracts.agent;

import java.math.BigDecimal;
import java.util.Optional;

/** Internal port for persisted, explicitly approved commands, never registered directly as an Agent tool. */
public interface DetectionExecutionApi {
    /** Recheck visibility without requiring the task to still be retryable. */
    void assertReadable(AgentActor actor, String taskId);
    record RetryPreview(String taskId, String resourceVersion, String status, String flowStatus,
                        String previousDispatchId, Integer modelId, BigDecimal threshold, int imageCount,
                        String impact) {}
    record RetryApproval(String taskId, String resourceVersion) {}
    /** status is the acceptance-time dispatch status, not a fresh detection result. */
    record Receipt(String commandId, String operation, String taskId, String dispatchId, String status) {}
    RetryPreview previewRetry(AgentActor actor, String taskId);
    Receipt retry(AgentActor actor, String requestId, String proposalId, RetryApproval approval);
    /** An empty receipt is not permission to replay an uncertain external write. */
    Optional<Receipt> receipt(AgentActor actor, String requestId);

    final class ResourceChanged extends IllegalStateException {
        public ResourceChanged() { super("任务已变化，请重新生成并确认检测提议"); }
    }
    final class NeedsReview extends IllegalStateException {
        public NeedsReview() { super("上次检测的执行结果尚未核实，暂不能创建新的检测派发"); }
    }
}
