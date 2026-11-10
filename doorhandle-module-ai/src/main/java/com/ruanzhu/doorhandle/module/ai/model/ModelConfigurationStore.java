package com.ruanzhu.doorhandle.module.ai.model;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.framework.persistence.JdbcTransactions;
import com.ruanzhu.doorhandle.framework.persistence.workflow.JdbcWorkflowStore;
import com.ruanzhu.doorhandle.framework.persistence.workflow.WorkflowDraft;
import com.ruanzhu.doorhandle.framework.persistence.workflow.WorkflowKind;
import com.ruanzhu.doorhandle.framework.persistence.workflow.WorkflowRecord;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;
import org.springframework.jdbc.core.JdbcTemplate;

/** Domain-owned access to persistent configuration control, revocations and operation receipts. */
final class ModelConfigurationStore {
    private static final String CONTROL = "MODEL_CONFIG_CONTROL";
    private static final String REVOCATION = "MODEL_KEY_REVOCATION";
    private final JdbcTemplate jdbc;
    private final ObjectMapper json;
    private final JdbcWorkflowStore workflows;

    ModelConfigurationStore(JdbcTemplate jdbc, ObjectMapper json) {
        this.jdbc = jdbc;
        this.json = json;
        workflows = new JdbcWorkflowStore(jdbc, json, ModelConfigurationWorkflow.protocols());
    }

    Map<String, Object> lockControl() {
        JdbcTransactions.requireActive(jdbc);
        // Existing encrypted history without its control record is an incomplete migration.
        // Only an empty configuration store may initialize the singleton. The unique-key
        // update serializes concurrent empty-store bootstraps without resetting its values.
        if (jdbc.queryForObject("SELECT COUNT(*) FROM runtime_state WHERE namespace=? AND owner_id=0 AND scope_key='GLOBAL'",
                Long.class, CONTROL) == 0) {
            jdbc.update("""
                    INSERT INTO runtime_state(namespace,owner_id,scope_key,revision,state_code,current_ref,counter_value,created_at)
                    SELECT ?,0,'GLOBAL',0,'READY','0',0,UTC_TIMESTAMP(6)
                    WHERE NOT EXISTS(SELECT 1 FROM llm_configuration)
                    ON DUPLICATE KEY UPDATE scope_key=VALUES(scope_key)
                    """, CONTROL);
        }
        var values = jdbc.queryForList("""
                SELECT current_ref,counter_value,revision,state_code FROM runtime_state
                WHERE namespace=? AND owner_id=0 AND scope_key='GLOBAL' FOR UPDATE
                """, CONTROL);
        if (values.size() != 1) throw invalidControl();
        var value = values.get(0);
        String activeText = Objects.toString(value.get("current_ref"), "");
        if (!activeText.matches("0|[1-9][0-9]{0,18}") || !(value.get("counter_value") instanceof Number counter)
                || !"READY".equals(value.get("state_code"))) throw invalidControl();
        long active;
        try { active = Long.parseLong(activeText); }
        catch (NumberFormatException invalid) { throw invalidControl(); }
        long maximum = jdbc.queryForObject("SELECT COALESCE(MAX(revision),0) FROM llm_configuration", Long.class);
        if (counter.longValue() < maximum || counter.longValue() < active || active == 0 && maximum != 0)
            throw invalidControl();
        long published = jdbc.queryForObject("SELECT COUNT(*) FROM llm_configuration WHERE status='PUBLISHED'", Long.class);
        if (published != (active == 0 ? 0 : 1)) throw invalidControl();
        if (active > 0 && jdbc.queryForObject("SELECT COUNT(*) FROM llm_configuration WHERE revision=? AND status='PUBLISHED'",
                Long.class, active) != 1) throw invalidControl();
        return Map.of("active_revision", active, "sequence_value", counter.longValue());
    }

    long activeRevision() {
        var values = jdbc.queryForList("SELECT current_ref FROM runtime_state WHERE namespace=? AND owner_id=0 AND scope_key='GLOBAL' AND state_code='READY'", CONTROL);
        if (values.size() != 1) throw invalidControl();
        try {
            long active = Long.parseLong(Objects.toString(values.get(0).get("current_ref"), ""));
            if (active <= 0) throw invalidControl();
            return active;
        } catch (NumberFormatException invalid) { throw invalidControl(); }
    }

    long nextRevision(Map<String, Object> locked) {
        JdbcTransactions.requireActive(jdbc);
        long previous = ((Number) locked.get("sequence_value")).longValue();
        long next = Math.addExact(previous, 1);
        if (jdbc.update("""
                UPDATE runtime_state SET counter_value=?,revision=revision+1,updated_at=UTC_TIMESTAMP(6)
                WHERE namespace=? AND owner_id=0 AND scope_key='GLOBAL' AND counter_value=?
                """, next, CONTROL, previous) != 1) throw invalidControl();
        return next;
    }

    void activate(long revision) {
        JdbcTransactions.requireActive(jdbc);
        if (revision < 1 || jdbc.queryForObject("SELECT COUNT(*) FROM llm_configuration WHERE revision=? AND status='PUBLISHED'",
                Long.class, revision) != 1) throw invalidControl();
        if (jdbc.update("""
                UPDATE runtime_state SET current_ref=?,revision=revision+1,updated_at=UTC_TIMESTAMP(6)
                WHERE namespace=? AND owner_id=0 AND scope_key='GLOBAL' AND counter_value>=?
                """, Long.toString(revision), CONTROL, revision) != 1) throw invalidControl();
    }

    boolean revoked(String provider, String fingerprint) {
        credential(provider, fingerprint);
        return jdbc.queryForObject("""
                SELECT COUNT(*) FROM runtime_state WHERE namespace=? AND owner_id=0 AND scope_key=?
                    AND provider=? AND credential_sha256=? AND state_code='REVOKED'
                """, Long.class, REVOCATION, provider + ":" + fingerprint, provider, fingerprint) > 0;
    }

    void revoke(String provider, String fingerprint, long actor, String request) {
        JdbcTransactions.requireActive(jdbc);
        credential(provider, fingerprint);
        if (actor <= 0 || request == null || request.isBlank() || request.length() > 128)
            throw new IllegalArgumentException("Invalid credential revocation identity");
        // The caller holds the configuration singleton lock. Preserve the first revocation.
        if (revoked(provider, fingerprint)) return;
        jdbc.update("""
                INSERT INTO runtime_state(namespace,owner_id,scope_key,revision,state_code,counter_value,
                    provider,credential_sha256,actor_user_id,request_id,created_at)
                VALUES(?,0,?,1,'REVOKED',0,?,?,?,?,UTC_TIMESTAMP(6))
                """, REVOCATION, provider + ":" + fingerprint, provider, fingerprint, actor, request);
    }

    List<Map<String, Object>> pendingRevocations() {
        return jdbc.queryForList("""
                SELECT provider,credential_sha256 AS key_sha256 FROM runtime_state
                WHERE namespace=? AND owner_id=0 AND state_code='REVOKED' AND counter_value=0
                ORDER BY created_at,scope_key LIMIT 100
                """, REVOCATION);
    }

    void propagated(String provider, String fingerprint) {
        credential(provider, fingerprint);
        jdbc.update("""
                UPDATE runtime_state SET counter_value=1,revision=revision+1,updated_at=UTC_TIMESTAMP(6)
                WHERE namespace=? AND owner_id=0 AND scope_key=? AND provider=? AND credential_sha256=?
                    AND state_code='REVOKED' AND counter_value=0
                """, REVOCATION, provider + ":" + fingerprint, provider, fingerprint);
    }

    Long receipt(long actor, String request, String action, String target) {
        var previous = workflows.findByRequest(WorkflowKind.MODEL_CONFIG_COMMAND, JdbcWorkflowStore.ownerScope(actor), request);
        if (previous.isEmpty()) return null;
        var value = workflows.payload(previous.get(), ModelConfigurationWorkflow.CommandV1.class);
        if (!action.equals(value.action()) || !target.equals(value.target()))
            throw ModelConfigurationService.fail(409, "请求编号已用于其他模型操作");
        if (!"COMPLETED".equals(previous.get().status()) || previous.get().resourceRevision() == null)
            throw new IllegalStateException("Incomplete model configuration receipt");
        return previous.get().resourceRevision();
    }

    void receipt(long actor, String request, String action, String target, long revision) {
        workflows.create(new WorkflowDraft(UUID.randomUUID().toString(), WorkflowKind.MODEL_CONFIG_COMMAND,
                JdbcWorkflowStore.ownerScope(actor), request, digest(action, target), actor, actor, null,
                "LLM_CONFIGURATION", Long.toString(revision), revision, null, null, "COMPLETED", null, 1,
                new ModelConfigurationWorkflow.CommandV1(action, target)));
    }

    record Replay<T>(boolean found,T response) { }
    record OriginalResult(com.fasterxml.jackson.databind.JsonNode response,com.ruanzhu.doorhandle.contracts.agent.OperationsAuditApi.ChangeReceipt receipt) { }
    <T> Replay<T> replay(long actor,String request,String action,String target,String digest,Class<T> responseType){
        JdbcTransactions.requireActive(jdbc);
        var rows=jdbc.queryForList("SELECT request_sha256,status,payload_json,result_version,result_json,result_sha256 FROM workflow_instance "
                +"WHERE kind='MODEL_CONFIG_COMMAND' AND idempotency_scope=? AND request_id=? FOR UPDATE",JdbcWorkflowStore.ownerScope(actor),request);
        if(rows.isEmpty())return new Replay<>(false,null);
        if(rows.size()!=1)throw new IllegalStateException("Ambiguous model configuration receipt");var row=rows.get(0);
        try{
            var payload=json.readValue((String)row.get("payload_json"),ModelConfigurationWorkflow.CommandV1.class);
            if(!payload.equals(new ModelConfigurationWorkflow.CommandV1(action,target))||!digest.equals(row.get("request_sha256")))
                throw ModelConfigurationService.fail(409,"请求编号已用于不同模型操作或内容");
            String body=(String)row.get("result_json");
            if(!"COMPLETED".equals(row.get("status"))||!(row.get("result_version") instanceof Number version)||version.intValue()!=1
                    ||body==null||!sha(body).equals(row.get("result_sha256")))
                throw ModelConfigurationService.fail(409,"旧命令原始响应未确认，请保留编号核对，禁止重复执行");
            var original=json.readValue(body,OriginalResult.class);
            if(original==null||original.response()==null||original.receipt()==null)throw ModelConfigurationService.fail(409,"模型命令原始回执未确认，请保留编号核对");
            AiCollaborationHistory.headers(original.receipt());
            return new Replay<>(true,json.treeToValue(original.response(),responseType));
        }catch(JsonProcessingException invalid){throw new IllegalStateException("Invalid original model command response",invalid);}
    }
    void complete(long actor,String request,String action,String target,String digest,long revision,Object response,com.ruanzhu.doorhandle.contracts.agent.OperationsAuditApi.ChangeReceipt receipt){
        JdbcTransactions.requireActive(jdbc);
        var stored=workflows.create(new WorkflowDraft(UUID.randomUUID().toString(),WorkflowKind.MODEL_CONFIG_COMMAND,
                JdbcWorkflowStore.ownerScope(actor),request,digest,actor,actor,null,"LLM_CONFIGURATION",Long.toString(revision),revision,
                null,null,"COMPLETED",null,1,new ModelConfigurationWorkflow.CommandV1(action,target)));
        try{
            if(receipt==null)receipt=new com.ruanzhu.doorhandle.contracts.agent.OperationsAuditApi.ChangeReceipt(null,null,Long.toString(changeVersion()));
            String body=json.writeValueAsString(new OriginalResult(json.valueToTree(response),receipt));if(body.getBytes(StandardCharsets.UTF_8).length>1048576)throw new IllegalArgumentException("Model command response too large");
            if(jdbc.update("UPDATE workflow_instance SET result_version=1,result_json=?,result_sha256=? WHERE id=? AND kind='MODEL_CONFIG_COMMAND' AND status='COMPLETED' AND result_json IS NULL",body,sha(body),stored.id())!=1)
                throw new IllegalStateException("Original model command response was already assigned");
            AiCollaborationHistory.headers(receipt);
        }catch(JsonProcessingException invalid){throw new IllegalStateException("Model command response cannot be encoded",invalid);}
    }
    long changeVersion(){return jdbc.queryForObject("SELECT revision FROM runtime_state WHERE namespace='MODEL_CONFIG_CONTROL' AND owner_id=0 AND scope_key='GLOBAL'",Long.class);}
    long advanceChangeVersion(){
        JdbcTransactions.requireActive(jdbc);
        if(jdbc.update("UPDATE runtime_state SET revision=revision+1,updated_at=UTC_TIMESTAMP(6) WHERE namespace='MODEL_CONFIG_CONTROL' AND owner_id=0 AND scope_key='GLOBAL' AND revision<9223372036854775807")!=1)
            throw new IllegalStateException("Model configuration change revision unavailable");
        return changeVersion();
    }
    private static String sha(String value){try{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8)));}catch(NoSuchAlgorithmException impossible){throw new IllegalStateException(impossible);}}

    Optional<WorkflowRecord> probe(long revision, String request) {
        return workflows.findByRequest(WorkflowKind.MODEL_JSON_PROBE, probeScope(revision), request);
    }

    String probeModel(WorkflowRecord record) {
        return workflows.payload(record, ModelConfigurationWorkflow.ProbeV1.class).modelId();
    }

    boolean startProbe(long revision, long owner, long actor, String model, String request) {
        String attempt = UUID.randomUUID().toString();
        var stored = workflows.create(new WorkflowDraft(attempt, WorkflowKind.MODEL_JSON_PROBE,
                probeScope(revision), request, digest(Long.toString(revision), model), owner, actor, null,
                "LLM_CONFIGURATION", Long.toString(revision), revision, null, null, "STARTED", null, 1,
                new ModelConfigurationWorkflow.ProbeV1(model)));
        // create() may return the idempotency winner after a unique-key race.
        // Only the newly persisted attempt is allowed to make the external call.
        return attempt.equals(stored.workflowId());
    }

    void finishProbe(long revision, String request, boolean passed) {
        var previous = probe(revision, request).orElseThrow();
        workflows.transition(previous, passed ? "PASSED" : "FAILED",
                workflows.payload(previous, ModelConfigurationWorkflow.ProbeV1.class), null, null, null);
    }

    record ProbeOutcome(ModelConfigurationService.ProbeResult response,com.ruanzhu.doorhandle.contracts.agent.OperationsAuditApi.ChangeReceipt receipt) { }
    void probeOutcome(long revision,String request,ModelConfigurationService.ProbeResult response,com.ruanzhu.doorhandle.contracts.agent.OperationsAuditApi.ChangeReceipt receipt){
        JdbcTransactions.requireActive(jdbc);if(receipt==null)throw new IllegalStateException("Required probe audit receipt missing");
        try{String body=json.writeValueAsString(new ProbeOutcome(response,receipt));
            if(jdbc.update("UPDATE workflow_instance SET result_version=1,result_json=?,result_sha256=? WHERE kind='MODEL_JSON_PROBE' AND idempotency_scope=? AND request_id=? AND status=?",body,sha(body),probeScope(revision),request,response.status())!=1)
                throw new IllegalStateException("Probe outcome receipt unavailable");
        }catch(JsonProcessingException invalid){throw new IllegalStateException("Probe outcome cannot be encoded",invalid);}
    }
    ModelConfigurationService.ProbeResult probeOutcome(long revision,String request){
        var rows=jdbc.queryForList("SELECT status,result_version,result_json,result_sha256 FROM workflow_instance WHERE kind='MODEL_JSON_PROBE' AND idempotency_scope=? AND request_id=?",probeScope(revision),request);
        if(rows.size()!=1)throw ModelConfigurationService.fail(409,"检查结果未确认，请保留编号核对");var row=rows.get(0);String body=(String)row.get("result_json");
        if(!(row.get("result_version") instanceof Number version)||version.intValue()!=1||body==null||!sha(body).equals(row.get("result_sha256")))
            throw ModelConfigurationService.fail(409,"旧检查原始回执未确认，禁止重新调用模型");
        try{var result=json.readValue(body,ProbeOutcome.class);
            if(result==null||result.response()==null||result.receipt()==null||result.response().revision()!=revision||!request.equals(result.response().requestId())||!Objects.equals(row.get("status"),result.response().status()))
                throw ModelConfigurationService.fail(409,"检查原始回执不一致");
            AiCollaborationHistory.headers(result.receipt());return result.response();
        }catch(JsonProcessingException invalid){throw new IllegalStateException("Invalid probe original response",invalid);}
    }

    boolean hasPassedProbe(long revision, String model) {
        return jdbc.queryForObject("""
                SELECT COUNT(*) FROM workflow_instance WHERE kind='MODEL_JSON_PROBE'
                    AND resource_revision=? AND model_probe_id=? AND status='PASSED'
                """, Long.class, revision, model) > 0;
    }

    List<ModelConfigurationService.ProbeResult> probes(long revision) {
        return jdbc.queryForList("""
                SELECT request_id,status,payload_json FROM workflow_instance WHERE kind='MODEL_JSON_PROBE'
                    AND resource_revision=? ORDER BY created_at DESC,id DESC LIMIT 50
                """, revision).stream().map(row -> {
                    try {
                        var payload = json.readValue((String) row.get("payload_json"), ModelConfigurationWorkflow.ProbeV1.class);
                        ModelConfigurationWorkflow.protocols().require(WorkflowKind.MODEL_JSON_PROBE).validatePayload(payload, 1);
                        return new ModelConfigurationService.ProbeResult(revision, payload.modelId(),
                                (String) row.get("request_id"), (String) row.get("status"));
                    } catch (JsonProcessingException invalid) { throw new IllegalStateException("Invalid model probe receipt", invalid); }
                }).toList();
    }

    static String digest(String... fields) {
        var framed = new StringBuilder();
        for (String field : fields) framed.append(field.getBytes(StandardCharsets.UTF_8).length).append(':').append(field);
        try { return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(framed.toString().getBytes(StandardCharsets.UTF_8))); }
        catch (NoSuchAlgorithmException impossible) { throw new IllegalStateException(impossible); }
    }

    private static String probeScope(long revision) {
        if (revision <= 0) throw new IllegalArgumentException("Invalid configuration revision");
        return "MODEL_CONFIG:" + revision;
    }

    private static void credential(String provider, String fingerprint) {
        if (provider == null || !Set.of("dashscope", "deepseek", "openai").contains(provider)
                || fingerprint == null || !fingerprint.matches("[a-f0-9]{64}"))
            throw new IllegalArgumentException("Invalid credential revocation identity");
    }

    private static IllegalStateException invalidControl() {
        return new IllegalStateException("模型配置控制记录与版本历史不一致 请完成迁移核对 禁止重新初始化已有配置");
    }
}
