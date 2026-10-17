package com.ruanzhu.doorhandle.contracts.agent;

import java.util.List;
import java.util.Map;

/** 仅授权报告查询和本人草稿写入；不提供提交、审批、放行或导出能力。 */
public interface QualityReportAgentApi {
    record Summary(String reportId,String taskId,String title,String status,int version,String ownerUsername) {}
    record Page(List<Summary> records,long total,int page,int size) {}
    record Detail(Summary report,String narrative,Map<String,Object> source,String decisionReason,String deciderUsername,String pagePath) {}
    record Origin(String requestId,String runId,String callId,String tool) {}
    record Draft(String taskId,String title,String narrative) {}
    record Edit(String reportId,int expectedVersion,String title,String narrative) {}
    record WriteReceipt(String reportId,int savedVersion,String tool,String status) {}
    default java.util.Optional<WriteReceipt> receipt(AgentActor actor,String runId,String callId,String tool){return java.util.Optional.empty();}
    Page list(AgentActor actor,int page,int size,String status,String keyword);
    Detail get(AgentActor actor,String reportId);
    Detail createDraft(AgentActor actor,Draft draft,Origin origin);
    Detail editDraft(AgentActor actor,Edit edit,Origin origin);
}
