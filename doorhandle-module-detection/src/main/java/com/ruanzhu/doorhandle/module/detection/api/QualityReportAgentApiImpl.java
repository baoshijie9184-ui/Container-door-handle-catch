package com.ruanzhu.doorhandle.module.detection.api;

import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory.Identity;
import com.ruanzhu.doorhandle.module.detection.dto.report.QualityReportDtos;
import com.ruanzhu.doorhandle.module.detection.service.QualityReportService;
import com.ruanzhu.doorhandle.module.detection.repository.ReportWorkflowRepository;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.*;
import java.time.LocalDateTime;
import java.util.*;

@Service
@Transactional(isolation=Isolation.READ_COMMITTED,rollbackFor=Exception.class)
public class QualityReportAgentApiImpl implements QualityReportAgentApi {
    @Override public java.util.Optional<WriteReceipt> receipt(AgentActor actor,String runId,String callId,String tool){
        identity(actor);var result=workflow.origin(actor.userId(),runId,callId,tool);
        if(result.isEmpty())return java.util.Optional.empty();var row=result.get();get(actor,row.resourceId());
        return java.util.Optional.of(new WriteReceipt(row.resourceId(),Math.toIntExact(row.resourceRevision()),tool,"DRAFT_WRITE_RECORDED"));
    }
    private final QualityReportService reports;
    private final ReportWorkflowRepository workflow;
    public QualityReportAgentApiImpl(QualityReportService reports,JdbcTemplate jdbc){this.reports=reports;this.workflow=new ReportWorkflowRepository(jdbc,new com.fasterxml.jackson.databind.ObjectMapper());}
    public Page list(AgentActor actor,int page,int size,String status,String keyword){
        var data=reports.list(identity(actor),page,size,status,keyword);
        @SuppressWarnings("unchecked") var rows=(List<QualityReportDtos.View>)data.get("records");
        return new Page(rows.stream().map(QualityReportAgentApiImpl::summary).toList(),((Number)data.get("total")).longValue(),page,size);
    }
    public Detail get(AgentActor actor,String id){return detail(reports.get(identity(actor),id));}
    public Detail createDraft(AgentActor actor,Draft draft,Origin origin){
        validate(origin,"create_report_draft");
        var result=reports.create(identity(actor),new QualityReportDtos.Create(draft.taskId(),draft.title(),draft.narrative(),origin.requestId()));
        link(actor,result,origin);return detail(result);
    }
    public Detail editDraft(AgentActor actor,Edit edit,Origin origin){
        validate(origin,"edit_report_draft");
        var result=reports.edit(identity(actor),edit.reportId(),new QualityReportDtos.Edit(edit.expectedVersion(),edit.title(),edit.narrative(),origin.requestId()));
        link(actor,result,origin);return detail(result);
    }
    private void link(AgentActor actor,QualityReportDtos.View result,Origin origin){
        workflow.origin(actor.userId(),origin.requestId(),result.reportId(),result.version(),result.ownerUserId(),origin.runId(),origin.callId(),origin.tool());
    }
    private static void validate(Origin origin,String tool){
        if(origin==null||origin.requestId()==null||!origin.requestId().matches("[A-Za-z0-9_-]{8,64}")||origin.runId()==null||!origin.runId().matches("[A-Za-z0-9_:.-]{1,128}")
                ||origin.callId()==null||!origin.callId().matches("[A-Za-z0-9_:.-]{1,160}")||!tool.equals(origin.tool()))throw new IllegalArgumentException("缺少报告工具来源");
    }
    private static Identity identity(AgentActor actor){if(actor==null)throw new SecurityException("缺少认证身份");return new Identity(actor.userId(),actor.username(),false);}
    private static Summary summary(QualityReportDtos.View row){return new Summary(row.reportId(),row.taskId(),row.title(),row.status(),row.version(),row.ownerUsername());}
    private static Detail detail(QualityReportDtos.View row){return new Detail(summary(row),row.narrative(),row.source(),row.decisionReason(),row.deciderUsername(),"/quality/reports?reportId="+row.reportId());}
}
