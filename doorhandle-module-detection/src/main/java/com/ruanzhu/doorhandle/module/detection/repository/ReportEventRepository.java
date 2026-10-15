package com.ruanzhu.doorhandle.module.detection.repository;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;
import java.time.LocalDateTime;
import java.util.*;

@Repository
public class ReportEventRepository {
    public record Entry(String eventId,String reportId,String eventType,String payload,String status,int attempts,String leaseToken) {}
    private final JdbcTemplate jdbc;
    public ReportEventRepository(JdbcTemplate jdbc){this.jdbc=jdbc;}
    private final org.springframework.jdbc.core.RowMapper<Entry> mapper=(r,n)->new Entry(r.getString("event_id"),r.getString("report_id"),r.getString("event_type"),r.getString("payload_json"),r.getString("delivery_status"),r.getInt("attempts"),r.getString("lease_token"));
    public List<Entry> due(LocalDateTime now,int limit){
        return jdbc.query("SELECT * FROM detection_report_outbox WHERE (delivery_status IN ('PENDING','RETRY') AND next_attempt_at<=?) OR (delivery_status='PROCESSING' AND lease_expires_at<=?) ORDER BY next_attempt_at,event_id LIMIT ?",mapper,now,now,limit);
    }
    public Entry get(String id){var rows=jdbc.query("SELECT * FROM detection_report_outbox WHERE event_id=?",mapper,id);return rows.isEmpty()?null:rows.get(0);}
    public List<Entry> siblings(String reportId){return jdbc.query("SELECT * FROM detection_report_outbox WHERE report_id=?",mapper,reportId);}
    public boolean claim(Entry entry,String token,LocalDateTime now,LocalDateTime expires){
        return jdbc.update("UPDATE detection_report_outbox SET delivery_status='PROCESSING',attempts=attempts+1,lease_token=?,lease_expires_at=?,last_error_code=NULL WHERE event_id=? AND attempts=? AND ((delivery_status IN ('PENDING','RETRY') AND next_attempt_at<=?) OR (delivery_status='PROCESSING' AND lease_expires_at<=?))",token,expires,entry.eventId(),entry.attempts(),now,now)==1;
    }
    public void defer(Entry entry,LocalDateTime next){
        jdbc.update("UPDATE detection_report_outbox SET next_attempt_at=?,delivery_status='RETRY',lease_token=NULL,lease_expires_at=NULL WHERE event_id=? AND attempts=? AND (delivery_status IN ('PENDING','RETRY') OR (delivery_status='PROCESSING' AND lease_token=?))",next,entry.eventId(),entry.attempts(),entry.leaseToken());
    }
    public boolean delivered(String id,String token,LocalDateTime now){
        return jdbc.update("UPDATE detection_report_outbox SET delivery_status='DELIVERED',delivered_at=?,lease_token=NULL,lease_expires_at=NULL,last_error_code=NULL WHERE event_id=? AND lease_token=? AND delivery_status='PROCESSING'",now,id,token)==1;
    }
    public boolean failed(String id,String token,String code,boolean permanent,LocalDateTime next){
        return jdbc.update("UPDATE detection_report_outbox SET delivery_status=?,next_attempt_at=?,last_error_code=?,lease_token=NULL,lease_expires_at=NULL WHERE event_id=? AND lease_token=? AND delivery_status='PROCESSING'",permanent?"FAILED":"RETRY",next,code,id,token)==1;
    }
}
