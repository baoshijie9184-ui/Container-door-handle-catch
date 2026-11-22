package com.ruanzhu.doorhandle.module.detection.service;

import com.ruanzhu.doorhandle.module.detection.entity.DetectionTask;
import com.ruanzhu.doorhandle.module.detection.security.DetectionTaskAccessPolicy;
import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.core.BeanPropertyRowMapper;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
@RequiredArgsConstructor
public class DetectionTraceQuery {
    public record Row(DetectionTask task, String traceRole, String sourceTaskId) {}

    public record Snapshot(List<Row> summaryRows, List<Row> pageRows) {}

    private static final String SUMMARY_COLUMNS = """
        t.id,t.task_id,t.capture_date,t.region,t.collector,t.work_order_no,t.batch_no,t.device_name,
        t.model_id,t.model_version,t.source_oss_prefix,t.result_oss_prefix,t.total_images,t.processed_images,
        t.successful_images,t.failed_images,t.defect_count,t.confirmed_defect_count,t.false_positive_count,
        t.review_status,t.disposition_status,t.flow_status,t.recheck_required,t.status,t.primary_defect_type,
        t.max_defect_severity,t.created_at,t.started_at,t.finished_at,t.updated_at
        """;

    private static final String BATCH_ROWS = """
        WITH readable AS (
            SELECT t.id,t.task_id,t.task_type,t.source_oss_prefix,t.status
            FROM detection_task t WHERE %s
        ), anchors AS (
            SELECT id,task_id,task_type,source_oss_prefix,status
            FROM detection_task o WHERE o.batch_no=:reference AND %s
        ), pairs AS (
            SELECT f.id AS formal_id,o.task_id AS source_id
            FROM detection_work_unit fw
            JOIN readable f ON fw.work_unit_id=f.task_id COLLATE utf8mb4_0900_ai_ci
            JOIN anchors o ON o.task_type IN ('BATCH','BATCH_DIRECT') AND o.status<>'CANCELLED'
            WHERE fw.strategy='OSS_FOLDER' AND COALESCE(fw.assignee_user_id,'')<>''
              AND f.task_type='OSS_FOLDER' AND f.status<>'CANCELLED' AND (%s)
        ), links AS (
            SELECT formal_id,MIN(source_id) AS source_id FROM pairs
            GROUP BY formal_id HAVING COUNT(DISTINCT source_id)=1
        ), trace_rows AS (
            SELECT o.id, NULL AS trace_source_id,
                   CASE WHEN EXISTS (SELECT 1 FROM links l WHERE l.source_id=o.task_id)
                        THEN 'SOURCE_UPLOAD' ELSE 'TASK' END AS trace_role
            FROM anchors o JOIN readable direct ON direct.id=o.id
            WHERE NOT EXISTS (SELECT 1 FROM links l WHERE l.formal_id=o.id)
            UNION ALL
            SELECT l.formal_id,source.task_id,'FORMAL_TASK'
            FROM links l LEFT JOIN readable source ON source.task_id=l.source_id
        )
        """;

    private static final String WORK_ORDER_ROWS = """
        WITH trace_rows AS (
            SELECT t.id,NULL AS trace_source_id,
                   CASE WHEN t.task_type='OSS_FOLDER' THEN 'FORMAL_TASK' ELSE 'TASK' END AS trace_role
            FROM detection_task t WHERE t.work_order_no=:reference AND %s
        )
        """;

    private static final String RESULT_ROWS = ", r.trace_role,r.trace_source_id FROM trace_rows r JOIN detection_task t ON t.id=r.id";

    private final NamedParameterJdbcTemplate jdbc;
    private final DetectionTaskAccessPolicy access;

    private final RowMapper<DetectionTask> taskMapper = new BeanPropertyRowMapper<>(DetectionTask.class);
    private final RowMapper<Row> rowMapper = (rs, index) -> new Row(taskMapper.mapRow(rs,index),
            rs.getString("trace_role"), rs.getString("trace_source_id"));

    public Snapshot read(boolean batch, String reference, int page, int size) {
        var scope = access.currentTaskReadSqlScope("t.");
        String predicate = BusinessDetectionTasks.filter("t.") + " AND (" + scope.predicate() + ")";
        String query = batch
                ? BATCH_ROWS.formatted(predicate,BusinessDetectionTasks.filter("o."),BusinessDetectionTasks.traceUploadLineage("o.","f."))
                : WORK_ORDER_ROWS.formatted(predicate);
        var arguments = new MapSqlParameterSource(scope.parameters()).addValue("reference",reference)
                .addValue("offset",((long)page - 1) * size).addValue("size",size);
        // Summaries need only small scalar fields. Image manifests and full task rows are fetched for one page.
        var summary = jdbc.query(query + "SELECT " + SUMMARY_COLUMNS + RESULT_ROWS + " ORDER BY t.created_at,t.id",arguments,rowMapper);
        String order = batch ? "CASE WHEN r.trace_role='FORMAL_TASK' THEN 0 ELSE 1 END,t.created_at,t.id" : "t.created_at,t.id";
        var details = summary.isEmpty() ? List.<Row>of() : jdbc.query(query + "SELECT t.*" + RESULT_ROWS
                + " ORDER BY " + order + " LIMIT :size OFFSET :offset",arguments,rowMapper);
        return new Snapshot(summary,details);
    }
}
