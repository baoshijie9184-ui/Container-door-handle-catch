package com.ruanzhu.doorhandle.framework.persistence.workflow;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.framework.persistence.JdbcTransactions;
import java.time.LocalDateTime;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import org.springframework.jdbc.core.JdbcTemplate;

/** Append-only events written in the same transaction as their authoritative state change. */
public final class JdbcAuditStore {
    private final JdbcTemplate jdbc;
    private final ObjectMapper json;
    private final Map<String, Class<?>> payloadTypes;
    public JdbcAuditStore(JdbcTemplate jdbc, ObjectMapper json) {
        this(jdbc,json,Map.of("CONVERSATION_INPUT",AuditPayloads.ConversationInputV1.class,
                "KNOWLEDGE",AuditPayloads.KnowledgeV1.class));
    }
    public JdbcAuditStore(JdbcTemplate jdbc,ObjectMapper json,Map<String,Class<?>> payloadTypes) {
        this.jdbc=jdbc; this.json=json; this.payloadTypes=Map.copyOf(payloadTypes);
    }
    public void validateSchema() {
        jdbc.queryForList("SELECT event_id,kind,owner_user_id,actor_user_id,resource_id,action,revision,"
                + "detection_model_id,content_sha256,policy_version,outcome,quantity,unit,request_scope,journal_run_id,research_export_run_id,observed_at,observation_model_id,observation_request_id,operation_scope,operation_domain,operation_result,payload_version,payload_json,occurred_at FROM audit_event WHERE 1=0");
    }
    public String append(AuditEvent event) {
        return append(event,null,null,null,null,null);
    }
    public String appendEvaluation(AuditEvent event,String policyVersion,boolean passed) {
        if(!"SKILL_EVALUATION".equals(event.kind())||!"SKILL".equals(event.resourceType())
                ||event.resourceId()==null||event.revision()==null||event.contentSha256()==null)
            throw new IllegalArgumentException("Skill evaluation requires its immutable version identity");
        WorkflowPayloads.text(policyVersion,64,"evaluation policy version");
        return append(event,policyVersion,passed?"PASSED":"FAILED",null,null,null);
    }
    public String appendObservation(AuditEvent event,long quantity,LocalDateTime observedAt) {
        if(!"MODEL_QUOTA_OBSERVATION".equals(event.kind())||!"LLM_MODEL".equals(event.resourceType())
                ||event.ownerUserId()==null||event.ownerUserId()<=0||!event.ownerUserId().equals(event.actorUserId())
                ||event.resourceId()==null||event.contentSha256()==null||quantity<0||observedAt==null)
            throw new IllegalArgumentException("Quota observation requires its actor, model, request digest, observed time and token quantity");
        WorkflowPayloads.text(event.resourceId(),180,"observed model");
        WorkflowPayloads.text(event.requestId(),64,"observation request");
        return append(event,null,null,quantity,"TOKENS","OWNER:"+event.actorUserId(),observedAt);
    }
    /** Immutable evidence authorization; a request identity cannot be reassigned to another run. */
    public String appendSkillSourceGrant(AuditEvent event) {
        if(!"SKILL_SOURCE_GRANT".equals(event.kind())||event.ownerUserId()==null||event.ownerUserId()<=0
                ||!event.ownerUserId().equals(event.actorUserId())||!"AGENT_RUN".equals(event.resourceType())
                ||event.runId()==null||!event.runId().equals(event.resourceId())||!event.runId().equals(event.requestId())
                ||event.contentSha256()==null)
            throw new IllegalArgumentException("Skill source grant requires an owned immutable run identity");
        WorkflowPayloads.text(event.runId(),128,"source grant run");
        return append(event,null,null,null,null,"OWNER:"+event.ownerUserId());
    }
    /** The original export identifier remains globally unique, independent of the audit event UUID. */
    public String appendResearchExport(AuditEvent event,long bytes) {
        if(!"RESEARCH_EXPORT".equals(event.kind())||event.ownerUserId()==null||event.ownerUserId()<=0
                ||!event.ownerUserId().equals(event.actorUserId())||!"RESEARCH_EXPORT".equals(event.resourceType())
                ||event.resourceId()==null||!event.resourceId().equals(event.requestId())||event.contentSha256()==null||bytes<0)
            throw new IllegalArgumentException("Research export requires its owned run, export identity and payload digest");
        WorkflowPayloads.text(event.resourceId(),36,"export identity");
        WorkflowPayloads.text(event.runId(),36,"export run");
        return append(event,null,null,bytes,"BYTES","RESEARCH_EXPORT");
    }
    public String appendMemoryPreference(AuditEvent event) {
        if(!"MEMORY_PREFERENCE".equals(event.kind())||event.ownerUserId()==null||event.ownerUserId()<=0
                ||!event.ownerUserId().equals(event.actorUserId())||!"MEMORY_PREFERENCE".equals(event.resourceType())
                ||!Long.toString(event.ownerUserId()).equals(event.resourceId())||event.revision()==null||event.revision()<0
                ||!"PREFERENCE_CHANGED".equals(event.action())||event.requestId()!=null)
            throw new IllegalArgumentException("Memory preference audit requires its owner and committed preference revision");
        return append(event,null,"SUCCEEDED",null,null,null);
    }
    public String appendMemoryOperation(AuditEvent event,String outcome) {
        if(!"MEMORY_OPERATION".equals(event.kind())||event.ownerUserId()==null||event.ownerUserId()<=0
                ||!"MEMORY_MUTATION".equals(event.resourceType())||event.resourceId()==null
                ||event.revision()==null||event.revision()<0||event.requestId()==null
                ||event.action()==null||!Set.of("DELETE","UPDATE","AUTOSAVE","REVIEW_DECISION","LIFECYCLE").contains(event.action())
                ||outcome==null||!Set.of("PENDING","DISPATCHED","UNKNOWN","SUCCEEDED","REJECTED").contains(outcome))
            throw new IllegalArgumentException("Memory operation audit requires its mutation identity, revision and committed state");
        WorkflowPayloads.text(event.resourceId(),64,"memory mutation identity");
        WorkflowPayloads.text(event.requestId(),64,"memory mutation request");
        return append(event,null,outcome,null,null,null);
    }
    /** Applicant ownership and decision actor differ; request identities belong to the acting account. */
    public String appendQuotaApplication(AuditEvent event,String outcome) {
        if(!"LLM_QUOTA_APPLICATION".equals(event.kind())||event.ownerUserId()==null||event.ownerUserId()<=0
                ||event.actorUserId()==null||event.actorUserId()<=0||!"LLM_QUOTA_APPLICATION".equals(event.resourceType())
                ||event.revision()==null||event.revision()<0||event.contentSha256()==null
                ||event.action()==null||outcome==null||!Map.of("APPLY","PENDING","APPROVE","APPROVED","REJECT","REJECTED","CANCEL","CANCELLED").containsKey(event.action())
                ||!Map.of("APPLY","PENDING","APPROVE","APPROVED","REJECT","REJECTED","CANCEL","CANCELLED").get(event.action()).equals(outcome))
            throw new IllegalArgumentException("Quota application audit requires its committed application and actor request");
        WorkflowPayloads.text(event.resourceId(),64,"quota application identity");
        WorkflowPayloads.text(event.requestId(),128,"quota application request");
        return append(event,null,outcome,null,null,"OWNER:"+event.actorUserId());
    }
    /** The original signed INT model key is a live CASCADE reference, not a historical string snapshot. */
    public String appendDetectionModelOperation(AuditEvent event,int modelId) {
        requireAnonymousOperation(event,"DETECTION_MODEL_OPERATION");
        if(!"DETECTION_MODEL".equals(event.resourceType())||event.resourceId()!=null)
            throw new IllegalArgumentException("Detection model operations require the typed model reference");
        return append(event,null,null,null,null,null,null,modelId);
    }
    public String appendInfraOperation(AuditEvent event,String outcome) {
        requireAnonymousOperation(event,"INFRA_OPERATION");
        if(event.resourceType()==null||event.resourceType().codePointCount(0,event.resourceType().length())>64
                ||event.resourceId()!=null&&event.resourceId().codePointCount(0,event.resourceId().length())>128
                ||outcome==null||outcome.codePointCount(0,outcome.length())>16)
            throw new IllegalArgumentException("Infrastructure operation resource or result exceeds its source contract");
        return append(event,null,outcome,null,null,null);
    }
    private static void requireAnonymousOperation(AuditEvent event,String kind) {
        if(!kind.equals(event.kind())||event.ownerUserId()!=null||event.actorUserId()!=null
                ||event.revision()!=null||event.requestId()!=null||event.sessionId()!=null||event.runId()!=null
                ||event.sequenceNo()!=null||event.contentSha256()!=null||event.action()==null
                ||event.action().codePointCount(0,event.action().length())>32)
            throw new IllegalArgumentException("Legacy operation identities must not be replaced by inferred users or requests");
    }
    private String append(AuditEvent event,String policyVersion,String outcome,Long quantity,String unit,String requestScope) {
        return append(event,policyVersion,outcome,quantity,unit,requestScope,null);
    }
    private String append(AuditEvent event,String policyVersion,String outcome,Long quantity,String unit,String requestScope,LocalDateTime observedAt) {
        return append(event,policyVersion,outcome,quantity,unit,requestScope,observedAt,null);
    }
    private String append(AuditEvent event,String policyVersion,String outcome,Long quantity,String unit,String requestScope,LocalDateTime observedAt,Integer detectionModelId) {
        JdbcTransactions.requireActive(jdbc);
        Class<?> type=payloadTypes.get(event.kind());
        if(type==null || !type.isRecord() || event.payloadVersion()!=1 || !type.isInstance(event.payload()))
            throw new IllegalArgumentException("Unregistered audit kind or payload version/type");
        WorkflowPayloads.text(event.action(),64,"audit action");
        if(event.contentSha256()!=null&&!event.contentSha256().matches("[a-f0-9]{64}"))
            throw new IllegalArgumentException("Invalid audit content digest");
        String id=UUID.randomUUID().toString();
        try {
            jdbc.update("""
                INSERT INTO audit_event(event_id,kind,owner_user_id,actor_user_id,resource_type,resource_id,
                  session_id,run_id,sequence_no,request_id,action,revision,content_sha256,occurred_at,payload_version,payload_json,
                  policy_version,outcome,quantity,unit,request_scope,observed_at,detection_model_id)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,COALESCE(?,UTC_TIMESTAMP(6)),?,?,?,?,?,?,?,?,?)
                """,id,event.kind(),event.ownerUserId(),event.actorUserId(),event.resourceType(),event.resourceId(),
                    event.sessionId(),event.runId(),event.sequenceNo(),event.requestId(),event.action(),event.revision(),
                    event.contentSha256(),event.occurredAt(),event.payloadVersion(),json.writeValueAsString(event.payload()),
                    policyVersion,outcome,quantity,unit,requestScope,observedAt,detectionModelId);
            return id;
        } catch(JsonProcessingException error) { throw new IllegalArgumentException("Cannot encode audit payload",error); }
    }
}
