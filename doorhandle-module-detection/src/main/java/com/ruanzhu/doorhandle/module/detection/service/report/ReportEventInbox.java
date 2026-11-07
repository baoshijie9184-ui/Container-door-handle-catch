package com.ruanzhu.doorhandle.module.detection.service.report;

import com.ruanzhu.doorhandle.module.detection.repository.ReportEventRepository;
import com.ruanzhu.doorhandle.module.detection.repository.ReportWorkflowRepository;
import com.ruanzhu.doorhandle.module.detection.repository.ReportWorkflowProtocols;
import com.ruanzhu.doorhandle.framework.persistence.workflow.WorkflowKind;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

/** 回执和只读事件状态同事务更新；消费不触发审批、任务放行或外部通知。 */
@Service
public class ReportEventInbox {
    private final JdbcTemplate jdbc;private final ReportEventRepository outbox;private final ReportEventCodec codec;private final TransactionTemplate tx;
    private final ReportWorkflowRepository reports;
    public ReportEventInbox(JdbcTemplate jdbc,ReportEventRepository outbox,ReportEventCodec codec,PlatformTransactionManager manager){
        this.jdbc=jdbc;this.outbox=outbox;this.codec=codec;this.tx=new TransactionTemplate(manager);
        this.reports=new ReportWorkflowRepository(jdbc,new com.fasterxml.jackson.databind.ObjectMapper());
    }
    public boolean receive(String key,String payload){
        var event=codec.decode(payload);
        if(!event.reportId().equals(key))throw new IllegalArgumentException("Invalid report event key");
        var original=outbox.get(event.eventId());
        if(original==null||!event.reportId().equals(original.reportId())||!event.eventType().equals(original.eventType())||!event.equals(codec.decode(original.payload())))
            throw new IllegalArgumentException("Report event is not bound to committed outbox");
        if(original.legacyClockUnresolved())throw new IllegalStateException("历史报告事件时间需核对，不能自动重放");
        String digest=codec.digest(event);
        return Boolean.TRUE.equals(tx.execute(status->{
            var delivery=reports.workflows().findByRequest(WorkflowKind.REPORT_DELIVERY,ReportWorkflowRepository.DELIVERY_SCOPE,event.eventId()).orElseThrow();
            if(delivery.legacyClockUnresolved())throw new IllegalStateException("历史报告事件时间需核对，不能自动重放");
            var prior=reports.workflows().findByRequest(WorkflowKind.REPORT_CONSUMPTION,ReportWorkflowRepository.CONSUMPTION_SCOPE,event.eventId());
            if(prior.isPresent()&&prior.get().legacyClockUnresolved())throw new IllegalStateException("历史报告接收回执时间需核对，不能自动确认或重放");
            var draft=ReportWorkflowRepository.draft(WorkflowKind.REPORT_CONSUMPTION,ReportWorkflowRepository.CONSUMPTION_SCOPE,event.eventId(),digest,
                    delivery.ownerUserId(),event.actorUserId(),event.reportId(),event.version(),null,"COMPLETED",null,
                    new ReportWorkflowProtocols.ConsumptionV1(event.eventType(),digest));
            var receipt=reports.workflows().create(draft);
            if(!draft.workflowId().equals(receipt.workflowId()))return false;
            String body=reports.encode(new ReportWorkflowProtocols.EventStateV1(event.reportId(),event.eventId(),event.version(),event.status()));
            // A report/version has one durable receipt; its read projection advances monotonically.
            jdbc.update("INSERT INTO runtime_state(namespace,owner_id,scope_key,revision,state_code,current_ref,counter_value,payload_version,payload_json,created_at,updated_at) VALUES('REPORT_EVENT_STATE',0,?,1,?,?,?,1,?,UTC_TIMESTAMP(6),UTC_TIMESTAMP(6)) ON DUPLICATE KEY UPDATE scope_key=scope_key",
                    event.reportId(),event.status(),event.eventId(),event.version(),body);
            jdbc.update("UPDATE runtime_state SET revision=revision+1,state_code=?,current_ref=?,counter_value=?,payload_json=?,updated_at=UTC_TIMESTAMP(6) WHERE namespace='REPORT_EVENT_STATE' AND owner_id=0 AND scope_key=? AND counter_value<?",
                    event.status(),event.eventId(),event.version(),body,event.reportId(),event.version());
            return true;
        }));
    }
}
