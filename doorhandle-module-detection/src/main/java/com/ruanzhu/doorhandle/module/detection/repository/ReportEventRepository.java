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
    public record Entry(String eventId,String reportId,String eventType,String payload,String status,int attempts,String leaseToken,
                        String clockStatus,Map<String,String> sourceWallTimes) {
        public Entry(String eventId,String reportId,String eventType,String payload,String status,int attempts,String leaseToken) {
            this(eventId,reportId,eventType,payload,status,attempts,leaseToken,null,Map.of());
        }
        public boolean legacyClockUnresolved(){return "UNRESOLVED".equals(clockStatus);}
        public Entry { sourceWallTimes=sourceWallTimes==null?Map.of():Collections.unmodifiableMap(new LinkedHashMap<>(sourceWallTimes)); }
    }
    private static final String READ="SELECT e.*,r.legacy_clock_json AS consumption_clock_json,r.legacy_source AS consumption_source,r.legacy_key AS consumption_source_key FROM workflow_instance e LEFT JOIN workflow_instance r ON r.kind='REPORT_CONSUMPTION' AND r.idempotency_scope='REPORT_CONSUMPTION' AND r.report_request_id=e.report_request_id AND r.resource_type='QUALITY_REPORT' AND r.resource_id=e.resource_id ";
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
        var clock=LegacyWorkflowClocks.read(r.getString("legacy_clock_json"),WorkflowKind.REPORT_DELIVERY,
                r.getString("legacy_source"),r.getString("legacy_key"));
        var consumedClock=LegacyWorkflowClocks.read(r.getString("consumption_clock_json"),WorkflowKind.REPORT_CONSUMPTION,
                r.getString("consumption_source"),r.getString("consumption_source_key"));
        if(clock==null)clock=consumedClock;
        return new Entry(r.getString("request_id"),r.getString("resource_id"),body.eventType(),body.eventJson(),r.getString("status"),r.getInt("attempts"),r.getString("claim_token"),
                clock==null?null:clock.clockStatus(),clock==null?Map.of():clock.sourceWallTimes());
    }
    public List<Entry> due(LocalDateTime now,int limit) {
        if(limit<1||limit>1000)throw new IllegalArgumentException("Invalid report delivery page size");
        return jdbc.query(READ+"WHERE e.kind='REPORT_DELIVERY' AND e.legacy_clock_json IS NULL AND r.legacy_clock_json IS NULL AND ((e.status IN ('PENDING','RETRY') AND COALESCE(e.next_attempt_at,e.created_at)<=?) OR (e.status='PROCESSING' AND e.lease_expires_at<=?)) ORDER BY COALESCE(e.next_attempt_at,e.created_at),e.request_id LIMIT ?",this::map,now,now,limit);
    }
    public Entry get(String id) {
        var rows=jdbc.query(READ+"WHERE e.kind='REPORT_DELIVERY' AND e.idempotency_scope='REPORT_DELIVERY' AND e.report_request_id=?",this::map,id);
        return rows.isEmpty()?null:rows.get(0);
    }
    public List<Entry> siblings(String reportId) {return jdbc.query(READ+"WHERE e.kind='REPORT_DELIVERY' AND e.resource_type='QUALITY_REPORT' AND e.resource_id=?",this::map,reportId);}
    public Entry claim(Entry entry,LocalDateTime now,LocalDateTime expires) {
        if(entry.legacyClockUnresolved())return null;
        try {
            return tx.execute(status->{
                var before=find(entry.eventId());if(before==null||before.legacyClockUnresolved())return null;
                var current=get(entry.eventId());if(current==null||current.legacyClockUnresolved()||current.attempts()!=entry.attempts())return null;
                Long due=jdbc.queryForObject("SELECT COUNT(*) FROM workflow_instance WHERE id=? AND legacy_clock_json IS NULL AND ((status IN ('PENDING','RETRY') AND COALESCE(next_attempt_at,created_at)<=UTC_TIMESTAMP(6)) OR (status='PROCESSING' AND lease_expires_at<=UTC_TIMESTAMP(6)))",Long.class,before.id());
                if(due!=1)return null;
                var body=workflows.payload(before,DeliveryV1.class);var lease=Duration.between(now,expires);
                if("PROCESSING".equals(before.status()))workflows.reclaim(before,"PROCESSING",body,null,null,lease);
                else workflows.claim(before,"PROCESSING",body,null,null,lease);
                return get(entry.eventId());
            });
        } catch(WorkflowConflictException conflict) { return null; }
    }
    public void defer(Entry entry,LocalDateTime next) {
        if(entry.legacyClockUnresolved())return;
        try {
            tx.executeWithoutResult(status->{
                var before=find(entry.eventId());if(before==null||before.legacyClockUnresolved())return;
                var current=get(entry.eventId());if(current==null||current.legacyClockUnresolved()||current.attempts()!=entry.attempts())return;
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
                if(claimed==null||claimed.legacyClockUnresolved()||token==null||!token.equals(claimed.claimToken())||!"PROCESSING".equals(claimed.status()))return false;
                var current=get(id);if(current==null||current.legacyClockUnresolved())return false;
                workflows.releaseClaim(claimed,state,workflows.payload(claimed,DeliveryV1.class),code,next);return true;
            }));
        } catch(WorkflowConflictException conflict) { return false; }
    }
    private WorkflowRecord find(String id) {return workflows.findByRequest(WorkflowKind.REPORT_DELIVERY,ReportWorkflowRepository.DELIVERY_SCOPE,id).orElse(null);}
}
