package com.ruanzhu.doorhandle.module.detection.api;

import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory.Identity;
import com.ruanzhu.doorhandle.module.detection.dto.report.QualityReportDtos;
import com.ruanzhu.doorhandle.module.detection.service.QualityReportService;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.*;
import java.time.LocalDateTime;
import java.util.*;

@Service
@Transactional(isolation=Isolation.READ_COMMITTED,rollbackFor=Exception.class)
public class QualityReportAgentApiImpl implements QualityReportAgentApi {
    @Override public java.util.Optional<WriteReceipt> receipt(AgentActor actor,String runId,String callId,String tool){
        var rows=jdbc.queryForList("SELECT report_id,report_version FROM detection_report_agent_origin WHERE actor_user_id=? AND run_id=? AND call_id=? AND tool_name=?",actor.userId(),runId,callId,tool);
        if(rows.isEmpty())return java.util.Optional.empty();String reportId=(String)rows.get(0).get("report_id");get(actor,reportId);
        return java.util.Optional.of(new WriteReceipt(reportId,((Number)rows.get(0).get("report_version")).intValue(),tool,"DRAFT_WRITE_RECORDED"));
    }
    private final QualityReportService reports;
    private final JdbcTemplate jdbc;
    public QualityReportAgentApiImpl(QualityReportService reports,JdbcTemplate jdbc){this.reports=reports;this.jdbc=jdbc;}
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
        var rows=jdbc.queryForList("SELECT run_id,tool_name,report_id,report_version FROM detection_report_agent_origin WHERE actor_user_id=? AND request_id=?",actor.userId(),origin.requestId());
        if(!rows.isEmpty()){
            var row=rows.get(0);
            if(!origin.runId().equals(row.get("run_id"))||!origin.tool().equals(row.get("tool_name"))||!result.reportId().equals(row.get("report_id"))||result.version()!=((Number)row.get("report_version")).intValue())
                throw new IllegalStateException("报告来源关联不一致");
            return;
        }
        if(jdbc.update("INSERT INTO detection_report_agent_origin(actor_user_id,request_id,report_id,report_version,run_id,call_id,tool_name,created_at) VALUES(?,?,?,?,?,?,?,?)",
                actor.userId(),origin.requestId(),result.reportId(),result.version(),origin.runId(),origin.callId(),origin.tool(),LocalDateTime.now())!=1)
            throw new IllegalStateException("报告来源记录失败");
    }
    private static void validate(Origin origin,String tool){
        if(origin==null||origin.requestId()==null||!origin.requestId().matches("[A-Za-z0-9_-]{8,64}")||origin.runId()==null||!origin.runId().matches("[A-Za-z0-9_:.-]{1,128}")
                ||origin.callId()==null||!origin.callId().matches("[A-Za-z0-9_:.-]{1,160}")||!tool.equals(origin.tool()))throw new IllegalArgumentException("缺少报告工具来源");
    }
    private static Identity identity(AgentActor actor){if(actor==null)throw new SecurityException("缺少认证身份");return new Identity(actor.userId(),actor.username(),false);}
    private static Summary summary(QualityReportDtos.View row){return new Summary(row.reportId(),row.taskId(),row.title(),row.status(),row.version(),row.ownerUsername());}
    private static Detail detail(QualityReportDtos.View row){return new Detail(summary(row),row.narrative(),row.source(),row.decisionReason(),row.deciderUsername(),"/quality/reports?reportId="+row.reportId());}
}
