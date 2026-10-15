package com.ruanzhu.doorhandle.contracts.agent;

import java.time.LocalDateTime;

/** 单体内原子分配门面；外部消息、上传和检测重试不属于此事务契约。 */
public interface DetectionAssignmentApi {
    record Command(String taskId, String qualityStation, String assignee, String dueAt, String assignmentRemark) {}
    record Values(String qualityStation, String assignee, String dueAt, String assignmentRemark, String flowStatus) {}
    record Preview(Command command, Values before, String resourceVersion) {}
    record Applied(String taskId, Values after) {}
    Preview preview(AgentActor actor, Command command);
    Applied apply(AgentActor actor, Command command, String expectedResourceVersion);

    final class ResourceChanged extends IllegalStateException {
        public ResourceChanged() { super("任务已变化，请重新生成分配提议"); }
    }
}
