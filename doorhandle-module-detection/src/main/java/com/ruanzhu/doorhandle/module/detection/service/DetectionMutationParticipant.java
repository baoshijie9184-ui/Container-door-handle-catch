package com.ruanzhu.doorhandle.module.detection.service;

import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import com.ruanzhu.doorhandle.contracts.collaboration.BusinessMutationParticipant;
import com.ruanzhu.doorhandle.contracts.collaboration.BusinessResourceAccess;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionTask;
import com.ruanzhu.doorhandle.module.detection.security.DetectionTaskAccessPolicy;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;
import java.util.*;

/** Task revisions are independent from assignee identity revisions and model business versions. */
@Component
public class DetectionMutationParticipant implements BusinessMutationParticipant, BusinessResourceAccess {
    private static final Set<String> ACTIONS = Set.of("createTask", "resumeUpload", "confirmUploaded", "advanceTaskFlow",
            "assignQualityTask", "reviewTask", "disposeTask", "submitReworkResult", "retryTask", "markUploaded", "claimTask", "authorizeClaimCandidates");
    private static final List<String> FIELDS = List.of("workflow_uuid", "batch_no", "work_order_no", "flow_status", "quality_station",
            "assignee", "assignment_remark", "due_at", "status", "stage", "model_id", "model_version", "threshold",
            "total_images", "processed_images", "successful_images", "failed_images", "defect_count", "primary_defect_type",
            "max_defect_severity", "review_status", "review_conclusion", "severity_level", "confirmed_defect_count",
            "false_positive_count", "review_remark", "reviewer", "disposition_status", "disposition_action", "disposition_remark",
            "disposition_operator", "recheck_required", "rework_result", "rework_operator", "rework_remark",
            "created_user_id", "assignee_user_id", "reviewer_user_id", "disposition_user_id", "rework_user_id",
            "assigned_by_user_id", "assignment_identity_revision", "claim_candidate_ids");
    private final JdbcTemplate jdbc;
    private final DetectionTaskAccessPolicy policy;
    public DetectionMutationParticipant(JdbcTemplate jdbc, DetectionTaskAccessPolicy policy) { this.jdbc = jdbc; this.policy = policy; }
    public boolean supports(String domain, String action) { return "DETECTION".equals(domain) && ACTIONS.contains(action); }
    public boolean creates(String action) { return "createTask".equals(action); }
    public String resourceId(String domain, String action, Object[] args, Object result) {
        if (!creates(action)) return (String) args[0];
        if (result instanceof com.ruanzhu.doorhandle.module.detection.dto.detection.CreateDetectionTaskResponse response) return response.getTaskId();
        return null;
    }
    public Snapshot capture(AgentActor actor, String domain, String action, String id, boolean lock) {
        if (id == null) return null;
        if (!id.matches("[A-Za-z0-9_-]{1,128}")) throw new IllegalArgumentException("任务编号无效");
        var rows = jdbc.queryForList("SELECT " + String.join(",", FIELDS) + ",version,created_by,assignee FROM detection_task WHERE task_id=?" + (lock ? " FOR UPDATE" : ""), id);
        if (rows.isEmpty()) return null;
        var row = rows.get(0); requireAccess(actor, id, row);
        var fields = new LinkedHashMap<String, Object>();
        for (String name : FIELDS) {
            Object value = row.get(name);
            if("claim_candidate_ids".equals(name))value=com.ruanzhu.doorhandle.module.detection.security.DetectionClaimCandidates.encode(com.ruanzhu.doorhandle.module.detection.security.DetectionClaimCandidates.read((String)value));
            if (value instanceof java.sql.Timestamp time) value = time.toLocalDateTime().toString();
            else if (value instanceof java.sql.Date date) value = date.toLocalDate().toString();
            else if (value instanceof java.time.temporal.TemporalAccessor time) value = time.toString();
            if (value instanceof String text && text.length() > 512) value = "sha256:" + sha(text);
            if (value instanceof Long number) value = number.toString();
            fields.put(name, value);
        }
        if (!(row.get("version") instanceof Number version) || version.longValue() < 0) throw new IllegalStateException("任务版本未完成升级");
        return new Snapshot("DETECTION_TASK", id, version.longValue(), fields, Set.of(), Set.of());
    }
    public Snapshot advanceVersion(Snapshot before, Snapshot after) {
        if (before == null || after == null || !Objects.equals(before.version(), after.version())) return after;
        long next = Math.addExact(before.version(), 1);
        if (jdbc.update("UPDATE detection_task SET version=? WHERE task_id=? AND version=?", next, after.resourceId(), before.version()) != 1)
            throw new com.ruanzhu.doorhandle.common.BusinessException(409, "任务版本已更新，请保留草稿后刷新");
        return new Snapshot(after.resourceType(), after.resourceId(), next, after.fields(), after.maskedFields(), after.secretFields());
    }
    public Object digestInput(String action, Object[] arguments) {
        // Only method command DTOs enter the canonical hash; no raw command is persisted in audit/receipt.
        return Arrays.asList(arguments);
    }
    public boolean mayRead(AgentActor actor, String scope, String domain, String type, String id) {
        if (!"ENTERPRISE".equals(scope) || !"DETECTION".equals(domain) || !"DETECTION_TASK".equals(type)
                || id == null || !id.matches("[A-Za-z0-9_-]{1,128}")) return false;
        var rows = jdbc.queryForList("SELECT created_by,assignee,status,flow_status,claim_candidate_ids FROM detection_task WHERE task_id=?", id);
        if (rows.isEmpty()) return false;
        try { requireAccess(actor, id, rows.get(0)); return true; } catch (SecurityException | org.springframework.security.access.AccessDeniedException denied) { return false; }
    }
    private void requireAccess(AgentActor actor, String id, Map<String, Object> row) {
        var task = new DetectionTask(); task.setTaskId(id); task.setCreatedBy((String) row.get("created_by")); task.setAssignee((String) row.get("assignee"));
        task.setStatus((String)row.get("status"));task.setFlowStatus((String)row.get("flow_status"));task.setClaimCandidateIds((String)row.get("claim_candidate_ids"));
        if (!policy.canAccess(task, actor)) throw new SecurityException("任务不存在或无访问权限");
    }
    private static String sha(String text) {
        try { return HexFormat.of().formatHex(java.security.MessageDigest.getInstance("SHA-256").digest(text.getBytes(java.nio.charset.StandardCharsets.UTF_8))); }
        catch (java.security.NoSuchAlgorithmException impossible) { throw new IllegalStateException(impossible); }
    }
}
