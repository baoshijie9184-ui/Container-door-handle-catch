package com.ruanzhu.doorhandle.module.detection.repository;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.framework.persistence.workflow.*;
import com.ruanzhu.doorhandle.module.detection.repository.ReportWorkflowProtocols.DeliveryV1;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.support.TransactionTemplate;
import java.time.Duration;
import java.time.LocalDateTime;
import java.util.*;

/** Short database transactions; the dispatcher holds no connection while publishing. */
@Repository
public class ReportEventRepository {
    public record Entry(String eventId,String reportId,String eventType,String payload,String status,int attempts,String leaseToken) { }
    private final JdbcTemplate jdbc;
    private final ReportWorkflowRepository reports;
    private final JdbcWorkflowStore workflows;
    private final TransactionTemplate tx;
    public ReportEventRepository(JdbcTemplate jdbc) {
        this.jdbc=jdbc;this.reports=new ReportWorkflowRepository(jdbc,new ObjectMapper());this.workflows=reports.workflows();
        this.tx=new TransactionTemplate(new DataSourceTransactionManager(Objects.requireNonNull(jdbc.getDataSource())));
    }
    private Entry map(java.sql.ResultSet r,int ignored)throws java.sql.SQLException {
        if(r.getInt("payload_version")!=1)throw new IllegalStateException("Unsupported report delivery payload");
        var body=reports.decode(r.getString("payload_json"),DeliveryV1.class);
        return new Entry(r.getString("request_id"),r.getString("resource_id"),body.eventType(),body.eventJson(),r.getString("status"),r.getInt("attempts"),r.getString("claim_token"));
    }
    public List<Entry> due(LocalDateTime now,int limit) {
        if(limit<1||limit>1000)throw new IllegalArgumentException("Invalid report delivery page size");
        return jdbc.query("SELECT * FROM workflow_instance WHERE kind='REPORT_DELIVERY' AND ((status IN ('PENDING','RETRY') AND COALESCE(next_attempt_at,created_at)<=?) OR (status='PROCESSING' AND lease_expires_at<=?)) ORDER BY COALESCE(next_attempt_at,created_at),request_id LIMIT ?",this::map,now,now,limit);
    }
    public Entry get(String id) {
        var rows=jdbc.query("SELECT * FROM workflow_instance WHERE kind='REPORT_DELIVERY' AND idempotency_scope='REPORT_DELIVERY' AND report_request_id=?",this::map,id);
        return rows.isEmpty()?null:rows.get(0);
    }
    public List<Entry> siblings(String reportId) {return jdbc.query("SELECT * FROM workflow_instance WHERE kind='REPORT_DELIVERY' AND resource_type='QUALITY_REPORT' AND resource_id=?",this::map,reportId);}
    public Entry claim(Entry entry,LocalDateTime now,LocalDateTime expires) {
        try {
            return tx.execute(status->{
                var before=find(entry.eventId());if(before==null)return null;
                var current=get(entry.eventId());if(current.attempts()!=entry.attempts())return null;
                Long due=jdbc.queryForObject("SELECT COUNT(*) FROM workflow_instance WHERE id=? AND ((status IN ('PENDING','RETRY') AND COALESCE(next_attempt_at,created_at)<=UTC_TIMESTAMP(6)) OR (status='PROCESSING' AND lease_expires_at<=UTC_TIMESTAMP(6)))",Long.class,before.id());
                if(due!=1)return null;
                var body=workflows.payload(before,DeliveryV1.class);var lease=Duration.between(now,expires);
                if("PROCESSING".equals(before.status()))workflows.reclaim(before,"PROCESSING",body,null,null,lease);
                else workflows.claim(before,"PROCESSING",body,null,null,lease);
                return get(entry.eventId());
            });
        } catch(WorkflowConflictException conflict) { return null; }
    }
    public void defer(Entry entry,LocalDateTime next) {
        try {
            tx.executeWithoutResult(status->{
                var before=find(entry.eventId());if(before==null)return;
                var current=get(entry.eventId());if(current.attempts()!=entry.attempts())return;
                // Expired claims are only reclaimed by claim(), never cleared by an ordering check.
                if(before.claimToken()!=null)return;
                if(!Set.of("PENDING","RETRY").contains(before.status()))return;
                var changed=workflows.transition(before,"RETRY",workflows.payload(before,DeliveryV1.class),null,null,null);
                jdbc.update("UPDATE workflow_instance SET next_attempt_at=? WHERE id=? AND revision=? AND fence=? AND claim_token IS NULL",next,changed.id(),changed.revision(),changed.fence());
            });
        } catch(WorkflowConflictException ignored) { /* Another dispatcher claimed this candidate. */ }
    }
    public boolean delivered(String id,String token,LocalDateTime now) {return release(id,token,"DELIVERED",null,null);}
    public boolean failed(String id,String token,String code,boolean permanent,LocalDateTime next) {return release(id,token,permanent?"FAILED":"RETRY",code,next);}
    private boolean release(String id,String token,String state,String code,LocalDateTime next) {
        try {
            return Boolean.TRUE.equals(tx.execute(status->{
                var claimed=find(id);
                if(claimed==null||token==null||!token.equals(claimed.claimToken())||!"PROCESSING".equals(claimed.status()))return false;
                workflows.releaseClaim(claimed,state,workflows.payload(claimed,DeliveryV1.class),code,next);return true;
            }));
        } catch(WorkflowConflictException conflict) { return false; }
    }
    private WorkflowRecord find(String id) {return workflows.findByRequest(WorkflowKind.REPORT_DELIVERY,ReportWorkflowRepository.DELIVERY_SCOPE,id).orElse(null);}
}
