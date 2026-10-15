package com.ruanzhu.doorhandle.module.detection.repository;

import org.springframework.jdbc.core.*;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Repository;
import java.time.LocalDateTime;
import java.util.*;

@Repository
public class QualityReportRepository {
    public record Row(String reportId, String previousReportId, long ownerUserId, String ownerUsername,
            String taskId, String title, String narrative, String status, int version, String sourceJson,
            String sourceSha256, String snapshotSha256, LocalDateTime submittedAt, LocalDateTime decidedAt,
            String deciderUsername, String decisionReason, LocalDateTime createdAt, LocalDateTime updatedAt) {}
    private final JdbcTemplate jdbc;
    private final NamedParameterJdbcTemplate named;
    public QualityReportRepository(JdbcTemplate jdbc) { this.jdbc=jdbc; this.named=new NamedParameterJdbcTemplate(jdbc); }
    private final RowMapper<Row> mapper=(r,n)->new Row(r.getString("report_id"),r.getString("previous_report_id"),
            r.getLong("owner_user_id"),r.getString("owner_username"),r.getString("task_id"),r.getString("title"),r.getString("narrative"),
            r.getString("status"),r.getInt("version"),r.getString("source_json"),r.getString("source_sha256"),r.getString("snapshot_sha256"),
            r.getObject("submitted_at",LocalDateTime.class),r.getObject("decided_at",LocalDateTime.class),r.getString("decider_username"),
            r.getString("decision_reason"),r.getObject("created_at",LocalDateTime.class),r.getObject("updated_at",LocalDateTime.class));
    public Row get(String id,boolean lock) {
        var rows=jdbc.query("SELECT * FROM detection_quality_report WHERE report_id=?"+(lock?" FOR UPDATE":""),mapper,id);
        return rows.isEmpty()?null:rows.get(0);
    }
    public List<Row> list(String where,Map<String,Object> parameters,int page,int size) {
        var p=new HashMap<>(parameters);p.put("limit",size);p.put("offset",(page-1)*size);
        return named.query("SELECT r.* FROM detection_quality_report r JOIN detection_task t ON t.task_id=r.task_id WHERE "+where+" ORDER BY r.id DESC LIMIT :limit OFFSET :offset",p,mapper);
    }
    public long count(String where,Map<String,Object> parameters) {
        return named.queryForObject("SELECT COUNT(*) FROM detection_quality_report r JOIN detection_task t ON t.task_id=r.task_id WHERE "+where,parameters,Long.class);
    }
    public JdbcTemplate jdbc() { return jdbc; }
}
