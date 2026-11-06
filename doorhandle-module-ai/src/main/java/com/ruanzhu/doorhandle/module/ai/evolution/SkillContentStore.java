package com.ruanzhu.doorhandle.module.ai.evolution;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.framework.persistence.JdbcTransactions;
import com.ruanzhu.doorhandle.framework.persistence.content.ContentKind;
import com.ruanzhu.doorhandle.framework.persistence.content.JdbcContentStore;
import com.ruanzhu.doorhandle.framework.persistence.workflow.AuditEvent;
import com.ruanzhu.doorhandle.framework.persistence.workflow.JdbcAuditStore;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.LocalDateTime;
import java.time.ZoneOffset;
import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;

/** Skill-specific content protocol; permissions and policy evaluation remain in the service. */
final class SkillContentStore {
    private static final String IDENTITY = "s.asset_id AS skill_id,s.owner_user_id,s.title AS name,s.required_role AS target_role,"
            + "s.current_version AS latest_version,s.published_version AS active_version,s.revision,s.lifecycle,s.use_count,"
            + "s.last_used_at,s.activated_at,s.created_at,s.updated_at";
    private static final String VERSION = "r.asset_id AS skill_id,r.version AS version_no,r.owner_user_id,r.request_id,r.request_sha256,"
            + "r.description_text,r.content_text AS instructions_text,r.tool_names_json,r.source_run_id,r.source_type,r.source_import_id,"
            + "r.manifest_json AS evidence_json,r.content_sha256,r.approval_status AS status,r.reviewer_user_id,r.review_reason,"
            + "r.submitted_at,r.reviewed_at,r.created_at";
    private final JdbcTemplate jdbc;
    private final ObjectMapper json;
    private final JdbcContentStore content;
    private final JdbcAuditStore audits;

    record EvaluationV1(String skillId, int version, String suiteVersion, Map<String,Object> result) { }
    record AuditV1(int version, String reason, String callId, boolean systemActor) { }
    record SourceGrantV1(String evidenceJson) { }
    record ImportReceiptV1(String importId,String packageSha256) { }
    record Revision(String skillId,int version,long owner,String requestId,String requestSha256,
                    String description,String instructions,String tools,String sourceType,String runId,
                    String importId,String evidence,String contentSha256) { }

    SkillContentStore(JdbcTemplate jdbc,ObjectMapper json) {
        this.jdbc=jdbc;this.json=json;this.content=new JdbcContentStore(jdbc);
        this.audits=new JdbcAuditStore(jdbc,json,Map.of("SKILL_EVALUATION",EvaluationV1.class,"SKILL_AUDIT",AuditV1.class,"SKILL_SOURCE_GRANT",SourceGrantV1.class));
    }
    void validateSchema() {
        jdbc.queryForList("SELECT asset_id,current_version,published_version FROM content_asset WHERE asset_kind='SKILL' AND 1=0");
        jdbc.queryForList("SELECT source_type,source_import_id,approval_status FROM content_revision WHERE asset_kind='SKILL' AND 1=0");
        jdbc.queryForList("SELECT owner_user_id,run_id,request_scope,request_id FROM audit_event WHERE kind='SKILL_SOURCE_GRANT' AND 1=0");
        jdbc.queryForList("SELECT namespace,owner_id,scope_key FROM runtime_state WHERE 1=0");
        jdbc.queryForList("SELECT policy_version,outcome FROM audit_event WHERE 1=0");
        audits.validateSchema();
    }
    List<Map<String,Object>> identities(String id,boolean lock) {
        if(lock)transaction();
        return jdbc.queryForList("SELECT "+IDENTITY+" FROM content_asset s WHERE s.asset_kind='SKILL' AND s.asset_id=?"+(lock?" FOR UPDATE":""),id);
    }
    List<Map<String,Object>> versions(String id) {
        return jdbc.queryForList("SELECT "+VERSION+" FROM content_revision r WHERE r.asset_kind='SKILL' AND r.asset_id=? ORDER BY r.version DESC",id);
    }
    List<Map<String,Object>> version(String id,int version) {
        return jdbc.queryForList("SELECT "+VERSION+" FROM content_revision r WHERE r.asset_kind='SKILL' AND r.asset_id=? AND r.version=?",id,version);
    }
    List<Map<String,Object>> requested(long owner,String request) {
        return jdbc.queryForList("SELECT asset_id AS skill_id,request_sha256 FROM content_revision WHERE asset_kind='SKILL' AND owner_user_id=? AND request_id=?",owner,request);
    }
    List<Map<String,Object>> imported(long owner,String importId) {
        return jdbc.queryForList("SELECT asset_id AS skill_id FROM content_revision WHERE asset_kind='SKILL' AND source_type='LINK' AND source_import_id=? AND owner_user_id=?",importId,owner);
    }
    List<Map<String,Object>> visible(long owner,boolean supervisor,String role) {
        String predicate=supervisor?"r.approval_status IN ('SUBMITTED','APPROVED','REJECTED')":"r.approval_status='APPROVED' AND s.required_role=?";
        return jdbc.queryForList("SELECT s.asset_id AS skill_id FROM content_asset s WHERE s.asset_kind='SKILL' AND (s.owner_user_id=? OR EXISTS(SELECT 1 FROM content_revision r WHERE r.asset_kind='SKILL' AND r.asset_id=s.asset_id AND "+predicate+")) ORDER BY s.id DESC LIMIT 50",
                supervisor?new Object[]{owner}:new Object[]{owner,role});
    }
    long visibleVersions(String id,boolean supervisor) {
        return jdbc.queryForObject("SELECT COUNT(*) FROM content_revision WHERE asset_kind='SKILL' AND asset_id=? AND "+(supervisor?"approval_status IN ('SUBMITTED','APPROVED','REJECTED')":"approval_status='APPROVED'"),Long.class,id);
    }
    List<Map<String,Object>> active(String role) {
        return jdbc.queryForList("SELECT "+IDENTITY+" FROM content_asset s WHERE s.asset_kind='SKILL' AND s.required_role=? AND s.published_version IS NOT NULL AND s.lifecycle IN ('ACTIVE','STALE') ORDER BY s.id LIMIT 30",role);
    }
    List<Map<String,Object>> published(String role,long owner,String selector) {
        String sql="SELECT "+IDENTITY+" FROM content_asset s JOIN content_revision r ON r.asset_id=s.asset_id AND r.asset_kind='SKILL' AND r.version=s.published_version WHERE s.asset_kind='SKILL' AND s.required_role=? AND s.lifecycle IN ('ACTIVE','STALE') AND r.approval_status='APPROVED' AND ((r.source_type='RUN' AND r.source_import_id IS NULL) OR (r.source_type='LINK' AND s.owner_user_id=?))";
        return selector==null?jdbc.queryForList(sql+" ORDER BY s.id LIMIT 100",role,owner)
                :jdbc.queryForList(sql+" AND (s.asset_id=? OR s.title=?) ORDER BY s.id LIMIT 2",role,owner,selector,selector);
    }
    void prepare(String id,long owner,String name,String role) {
        content.prepare(new JdbcContentStore.AssetDraft(id,ContentKind.SKILL,owner,name,null,"PRIVATE",role,null,now()));
    }
    void append(Revision input) {
        transaction();
        var rows=identities(input.skillId(),true);
        if(rows.size()!=1||number(rows.get(0).get("owner_user_id"))!=input.owner())throw new IllegalStateException("Skill version owner mismatch");
        Object previous=rows.get(0).get("latest_version");
        if(input.version()!=(previous==null?1:number(previous)+1))throw new IllegalStateException("Skill versions must append in order");
        byte[] body=input.instructions().getBytes(StandardCharsets.UTF_8);
        jdbc.update("""
            INSERT INTO content_revision(asset_id,asset_kind,version,owner_user_id,creator_user_id,title,
              request_id,request_sha256,description_text,content_text,tool_names_json,source_run_id,source_type,
              source_import_id,manifest_json,manifest_sha256,content_sha256,stored_content_sha256,byte_length,
              media_type,approval_status,created_at)
            VALUES(?,'SKILL',?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'text/markdown','DRAFT',UTC_TIMESTAMP(6))
            """,input.skillId(),input.version(),input.owner(),input.owner(),rows.get(0).get("name"),input.requestId(),input.requestSha256(),
                input.description(),input.instructions(),input.tools(),input.runId(),input.sourceType(),input.importId(),input.evidence(),
                sha(input.evidence().getBytes(StandardCharsets.UTF_8)),input.contentSha256(),sha(body),body.length);
    }
    void advance(String id,int version) {
        transaction();
        // MySQL evaluates SET assignments left to right: inspect the previous pointer before replacing it.
        int changed=jdbc.update("UPDATE content_asset SET revision=CASE WHEN current_version IS NULL THEN revision ELSE revision+1 END,lifecycle=CASE WHEN current_version IS NULL THEN 'ACTIVE' ELSE lifecycle END,current_version=?,updated_at=UTC_TIMESTAMP(6) WHERE asset_kind='SKILL' AND asset_id=? AND (current_version IS NULL AND ?=1 OR current_version=?) AND EXISTS(SELECT 1 FROM content_revision r WHERE r.asset_id=content_asset.asset_id AND r.asset_kind='SKILL' AND r.version=?)",version,id,version,version-1,version);
        if(changed!=1)throw new IllegalStateException("Skill version pointer changed concurrently");
    }
    void status(String id,int version,String status) {
        transaction();jdbc.update("UPDATE content_revision SET approval_status=? WHERE asset_kind='SKILL' AND asset_id=? AND version=?",status,id,version);
    }
    void submit(String id,int version) {
        transaction();jdbc.update("UPDATE content_revision SET approval_status='SUBMITTED',submitted_at=UTC_TIMESTAMP(6) WHERE asset_kind='SKILL' AND asset_id=? AND version=?",id,version);
    }
    void review(String id,int version,boolean approved,long reviewer,String reason) {
        transaction();jdbc.update("UPDATE content_revision SET approval_status=?,reviewer_user_id=?,review_reason=?,reviewed_at=UTC_TIMESTAMP(6) WHERE asset_kind='SKILL' AND asset_id=? AND version=?",approved?"APPROVED":"REJECTED",reviewer,reason,id,version);
    }
    void publish(String id,int version) {
        transaction();int changed=jdbc.update("UPDATE content_asset SET published_version=?,revision=revision+1,lifecycle='ACTIVE',visibility='ROLE',activated_at=UTC_TIMESTAMP(6),updated_at=UTC_TIMESTAMP(6) WHERE asset_kind='SKILL' AND asset_id=? AND EXISTS(SELECT 1 FROM content_revision r WHERE r.asset_id=content_asset.asset_id AND r.asset_kind='SKILL' AND r.version=? AND r.approval_status='APPROVED')",version,id,version);
        if(changed!=1)throw new IllegalStateException("Only an approved immutable skill version may be published");
    }
    void archive(String id) {
        transaction();jdbc.update("UPDATE content_asset SET published_version=NULL,lifecycle='ARCHIVED',visibility='PRIVATE',revision=revision+1,updated_at=UTC_TIMESTAMP(6) WHERE asset_kind='SKILL' AND asset_id=?",id);
    }
    void withdraw(String id) {
        transaction();jdbc.update("UPDATE content_revision SET approval_status='DRAFT',submitted_at=NULL WHERE asset_kind='SKILL' AND asset_id=? AND approval_status='SUBMITTED'",id);
    }
    void bump(String id) { transaction();jdbc.update("UPDATE content_asset SET revision=revision+1,updated_at=UTC_TIMESTAMP(6) WHERE asset_kind='SKILL' AND asset_id=?",id); }
    int recordUse(String id,int version) {
        transaction();return jdbc.update("UPDATE content_asset SET use_count=use_count+1,last_used_at=UTC_TIMESTAMP(6),lifecycle='ACTIVE' WHERE asset_kind='SKILL' AND asset_id=? AND published_version=? AND lifecycle IN ('ACTIVE','STALE')",id,version);
    }
    List<Map<String,Object>> stale(LocalDateTime before) {
        transaction();return jdbc.queryForList("SELECT "+IDENTITY+" FROM content_asset s WHERE s.asset_kind='SKILL' AND s.published_version IS NOT NULL AND s.lifecycle IN ('ACTIVE','STALE') AND COALESCE(s.last_used_at,s.activated_at)<? ORDER BY s.id LIMIT 100 FOR UPDATE",before);
    }
    void markStale(String id) { transaction();jdbc.update("UPDATE content_asset SET lifecycle='STALE',revision=revision+1,updated_at=UTC_TIMESTAMP(6) WHERE asset_kind='SKILL' AND asset_id=?",id); }
    List<Map<String,Object>> sources(long owner) {
        return sourceRows(jdbc.queryForList("SELECT run_id,content_sha256 AS evidence_sha256,payload_version,payload_json,occurred_at AS captured_at FROM audit_event WHERE kind='SKILL_SOURCE_GRANT' AND owner_user_id=? ORDER BY id DESC LIMIT 50",owner));
    }
    List<Map<String,Object>> source(long owner,String runId) {
        return sourceRows(jdbc.queryForList("SELECT run_id,content_sha256 AS evidence_sha256,payload_version,payload_json,occurred_at AS captured_at FROM audit_event WHERE kind='SKILL_SOURCE_GRANT' AND owner_user_id=? AND run_id=?",owner,runId));
    }
    private List<Map<String,Object>> sourceRows(List<Map<String,Object>> rows) {
        for(var row:rows){
            requirePayload(row);var payload=map(row.remove("payload_json"));
            if(!(payload.get("evidenceJson") instanceof String evidence))throw new IllegalStateException("Invalid skill source grant");
            row.put("evidence_json",evidence);
        }
        return rows;
    }
    void capture(long owner,String runId,String evidence,String digest) {
        transaction();
        // Consent is an immutable fact, not a versioned document. Serialize its original owner/run identity.
        jdbc.update("INSERT INTO runtime_state(namespace,owner_id,scope_key,revision) VALUES('SKILL_SOURCE',?,?,0) ON DUPLICATE KEY UPDATE owner_id=VALUES(owner_id)",owner,runId);
        jdbc.queryForObject("SELECT revision FROM runtime_state WHERE namespace='SKILL_SOURCE' AND owner_id=? AND scope_key=? FOR UPDATE",Long.class,owner,runId);
        if(!source(owner,runId).isEmpty())return;
        audits.appendSkillSourceGrant(new AuditEvent("SKILL_SOURCE_GRANT",owner,owner,"AGENT_RUN",runId,null,runId,null,runId,
                "GRANT_SKILL_SOURCE",null,digest,null,1,new SourceGrantV1(evidence)));
    }
    void evaluation(String id,int version,long owner,long actor,String hash,String suite,boolean passed,Map<String,Object> result) {
        audits.appendEvaluation(new AuditEvent("SKILL_EVALUATION",owner,actor,"SKILL",id,null,null,null,null,"EVALUATE",(long)version,hash,null,1,new EvaluationV1(id,version,suite,result)),suite,passed);
    }
    boolean evaluated(String id,int version,String hash,String suite) {
        return jdbc.queryForObject("SELECT COUNT(*) FROM audit_event WHERE kind='SKILL_EVALUATION' AND resource_type='SKILL' AND resource_id=? AND revision=? AND content_sha256=? AND policy_version=? AND outcome='PASSED'",Long.class,id,version,hash,suite)>0;
    }
    void audit(String id,int version,long actor,String action,int revision,String hash,String reason,String runId,String callId) {
        Long owner=jdbc.queryForObject("SELECT owner_user_id FROM content_asset WHERE asset_kind='SKILL' AND asset_id=?",Long.class,id);
        audits.append(new AuditEvent("SKILL_AUDIT",owner,actor==0?null:actor,"SKILL",id,null,runId,null,null,action,(long)revision,hash,null,1,new AuditV1(version,reason,callId,actor==0)));
    }
    List<Map<String,Object>> evaluations(String id) {
        var rows=jdbc.queryForList("SELECT revision AS version_no,policy_version AS suite_version,outcome,payload_version,payload_json,occurred_at AS created_at FROM audit_event WHERE kind='SKILL_EVALUATION' AND resource_type='SKILL' AND resource_id=? ORDER BY id DESC LIMIT 50",id);
        for(var row:rows){ requirePayload(row);var payload=map(row.remove("payload_json"));row.put("result",payload.get("result"));row.put("passed","PASSED".equals(row.remove("outcome"))); }
        return rows;
    }
    List<Map<String,Object>> auditHistory(String id) {
        var rows=jdbc.queryForList("SELECT COALESCE(actor_user_id,0) AS actor_user_id,action AS action_name,revision,run_id,payload_version,payload_json,occurred_at AS created_at FROM audit_event WHERE kind='SKILL_AUDIT' AND resource_type='SKILL' AND resource_id=? ORDER BY id DESC LIMIT 100",id);
        for(var row:rows){ requirePayload(row);var payload=map(row.remove("payload_json"));row.put("version_no",payload.get("version"));row.put("reason",payload.get("reason"));row.put("call_id",payload.get("callId")); }
        return rows;
    }
    private void requirePayload(Map<String,Object> row) { if(number(row.remove("payload_version"))!=1)throw new IllegalStateException("Unsupported skill audit payload version"); }
    private Map<String,Object> map(Object value) {
        try { return json.readValue(value instanceof byte[] bytes?new String(bytes,StandardCharsets.UTF_8):value.toString(),new TypeReference<LinkedHashMap<String,Object>>(){}); }
        catch(Exception error){throw new IllegalStateException("Invalid skill audit payload",error);}
    }
    private void transaction() { JdbcTransactions.requireActive(jdbc); }
    private static long number(Object value) { return ((Number)value).longValue(); }
    private static LocalDateTime now() { return LocalDateTime.now(ZoneOffset.UTC); }
    private static String sha(byte[] bytes) {
        try { return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes)); }
        catch(java.security.NoSuchAlgorithmException error){throw new IllegalStateException(error);}
    }
}
