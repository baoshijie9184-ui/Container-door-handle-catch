package com.ruanzhu.doorhandle.module.ai.action;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.framework.persistence.JdbcTransactions;
import com.ruanzhu.doorhandle.framework.persistence.workflow.WorkflowKind;
import com.ruanzhu.doorhandle.framework.persistence.workflow.WorkflowProtocol;
import com.ruanzhu.doorhandle.framework.persistence.workflow.WorkflowProtocols;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.LocalDateTime;
import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;

/** Owner-scoped approval state and immutable audit evidence. No automatic replay of uncertain execution. */
final class AgentActionPersistence {
    record ProposalV1(String callId,String operation,String resourceVersion,String commandJson,String beforeJson,
                      String policyVersion,String legacyCreatedAt,String legacyExpiresAt,String legacyDecidedAt,String sourceUtcOffset) { }
    record ResultV1(String resultJson) { }
    record AuditV1(String actorRole,String resourceId,String reasonCode,String legacyId,String legacyOccurredAt,String sourceUtcOffset) { }
    record Row(long id,String actionId,long userId,String runId,String sessionId,String resourceId,String digest,
               String status,long version,String reasonCode,LocalDateTime createdAt,LocalDateTime expiresAt,
               LocalDateTime decidedAt,ProposalV1 proposal,String resultJson) { }
    record AuditRow(long id,String eventType,String actorRole,String result,String reasonCode,LocalDateTime occurredAt) { }
    private static final Set<String> TERMINAL=Set.of("SUCCEEDED","REJECTED","CANCELLED","EXPIRED","INVALIDATED");
    private final JdbcTemplate jdbc;
    private final ObjectMapper json;
    private final WorkflowProtocol<ProposalV1> protocol;

    AgentActionPersistence(JdbcTemplate jdbc,ObjectMapper mapper) {
        this.jdbc=jdbc;
        json=mapper.copy().setSerializationInclusion(JsonInclude.Include.ALWAYS)
                .enable(DeserializationFeature.FAIL_ON_MISSING_CREATOR_PROPERTIES);
        protocol=new WorkflowProtocol<>(WorkflowKind.AGENT_ACTION,1,ProposalV1.class,Set.of("PENDING"),TERMINAL,
                Map.of("PENDING",Set.of("SUCCEEDED","REJECTED","CANCELLED","EXPIRED","INVALIDATED","EXECUTING"),
                        "EXECUTING",Set.of("SUCCEEDED","CANCELLED","NEEDS_REVIEW"),
                        "NEEDS_REVIEW",Set.of("EXECUTING","SUCCEEDED","CANCELLED")),this::validate,false);
        WorkflowProtocols.defaults().with(protocol).require(WorkflowKind.AGENT_ACTION);
    }

    void validateSchema() {
        jdbc.queryForList("SELECT agent_action_digest,agent_action_call_id,agent_action_operation,confirmation_recorded_at FROM workflow_instance WHERE 1=0");
        jdbc.queryForList("SELECT kind,owner_user_id,policy_version,outcome,payload_version FROM audit_event WHERE 1=0");
    }

    Row find(long owner,String actionId,boolean locked) {
        if(locked)JdbcTransactions.requireActive(jdbc);
        var rows=jdbc.query("SELECT * FROM workflow_instance WHERE kind='AGENT_ACTION' AND owner_user_id=? AND request_id=?"+(locked?" FOR UPDATE":""),this::row,owner,actionId);
        return rows.isEmpty()?null:rows.get(0);
    }

    List<Row> byArguments(long owner,String run,String digest) {
        JdbcTransactions.requireActive(jdbc);
        return jdbc.query("SELECT * FROM workflow_instance WHERE kind='AGENT_ACTION' AND owner_user_id=? AND run_id=? AND agent_action_digest=? FOR UPDATE",this::row,owner,run,digest);
    }

    List<Row> pendingResource(long owner,String resource) {
        JdbcTransactions.requireActive(jdbc);
        return jdbc.query("SELECT * FROM workflow_instance WHERE kind='AGENT_ACTION' AND owner_user_id=? AND resource_id=? AND status='PENDING' FOR UPDATE",this::row,owner,resource);
    }

    List<Row> pendingCreations(long owner,String run) {
        JdbcTransactions.requireActive(jdbc);
        return jdbc.query("SELECT * FROM workflow_instance WHERE kind='AGENT_ACTION' AND owner_user_id=? AND run_id=? AND agent_action_operation='CREATE_DETECTION' AND status='PENDING' FOR UPDATE",this::row,owner,run);
    }

    int count(long owner,String run) {
        return Objects.requireNonNull(jdbc.queryForObject("SELECT COUNT(*) FROM workflow_instance WHERE kind='AGENT_ACTION' AND owner_user_id=? AND run_id=?",Integer.class,owner,run));
    }

    List<String> ids(long owner,String session,String run,int limit) {
        if(limit<1||limit>100)throw new IllegalArgumentException("Invalid approval page size");
        var args=new ArrayList<Object>();args.add(owner);String where="kind='AGENT_ACTION' AND owner_user_id=?";
        if(session!=null){where+=" AND session_id=?";args.add(session);}
        if(run!=null){where+=" AND run_id=?";args.add(run);}
        args.add(limit);
        return jdbc.queryForList("SELECT request_id FROM workflow_instance WHERE "+where+" ORDER BY created_at DESC,request_id DESC LIMIT ?",String.class,args.toArray());
    }

    void create(String actionId,long owner,String run,String session,String call,String operation,String resource,
                String resourceVersion,String digest,String command,String before,String policy,LocalDateTime expires) {
        JdbcTransactions.requireActive(jdbc);
        var payload=new ProposalV1(call,operation,resourceVersion,command,before,policy,null,null,null,null);
        protocol.validatePayload(payload,1);protocol.requireInitial("PENDING");
        jdbc.update("""
                INSERT INTO workflow_instance(workflow_id,kind,idempotency_scope,request_id,request_sha256,owner_user_id,
                  actor_user_id,resource_type,resource_id,session_id,run_id,status,revision,payload_version,payload_json,expires_at)
                VALUES(?,'AGENT_ACTION','AGENT_ACTION',?,?,?,?,'AGENT_ACTION',?,?,?,'PENDING',1,1,?,?)
                ""","agent-action:"+actionId,actionId,digest,owner,owner,resource,session,run,write(payload),expires);
    }

    void result(long owner,String actionId,long version,String body) {
        JdbcTransactions.requireActive(jdbc);validateJson(body);
        String result=write(new ResultV1(body));
        if(jdbc.update("UPDATE workflow_instance SET result_version=1,result_json=?,result_sha256=? WHERE kind='AGENT_ACTION' AND owner_user_id=? AND request_id=? AND revision=?",
                result,sha(result),owner,actionId,version)!=1)throw changed();
    }

    void close(long owner,String actionId,long version,String state,String reason) {
        JdbcTransactions.requireActive(jdbc);protocol.requireTransition("PENDING",state);
        LocalDateTime now=now();
        if(jdbc.update("UPDATE workflow_instance SET status=?,error_code=?,revision=revision+1,confirmation_recorded_at=?,updated_at=?,finished_at=? "
                        +"WHERE kind='AGENT_ACTION' AND owner_user_id=? AND request_id=? AND status='PENDING' AND revision=?",
                state,reason,now,now,TERMINAL.contains(state)?now:null,owner,actionId,version)!=1)throw changed();
    }

    void reconcile(long owner,String actionId,long version,String before,String state,String reason,String body) {
        JdbcTransactions.requireActive(jdbc);protocol.requireTransition(before,state);validateJson(body);
        LocalDateTime now=now();String result=write(new ResultV1(body));
        if(jdbc.update("UPDATE workflow_instance SET status=?,error_code=?,result_version=1,result_json=?,result_sha256=?,revision=revision+1,updated_at=?,finished_at=? "
                        +"WHERE kind='AGENT_ACTION' AND owner_user_id=? AND request_id=? AND status=? AND revision=?",
                state,reason,result,sha(result),now,TERMINAL.contains(state)?now:null,owner,actionId,before,version)!=1)throw changed();
    }

    void appendAudit(long owner,String actionId,String run,String event,String role,String resource,String digest,String policy,String result,String reason) {
        JdbcTransactions.requireActive(jdbc);
        var payload=new AuditV1(role,resource,reason,null,null,null);
        jdbc.update("""
                INSERT INTO audit_event(event_id,kind,owner_user_id,actor_user_id,resource_type,resource_id,run_id,action,
                  content_sha256,policy_version,outcome,payload_version,payload_json)
                VALUES(?,'AGENT_ACTION',?,?,'AGENT_ACTION',?,?,?,?,?,?,1,?)
                """,UUID.randomUUID().toString(),owner,owner,actionId,run,event,digest,policy,result,write(payload));
    }

    List<AuditRow> audits(long owner,String actionId) {
        return jdbc.query("SELECT id,action,outcome,occurred_at,payload_version,payload_json FROM audit_event WHERE kind='AGENT_ACTION' AND owner_user_id=? AND resource_id=? ORDER BY id",(rs,n)->{
            if(rs.getInt("payload_version")!=1)throw changed();
            var payload=read(rs.getString("payload_json"),AuditV1.class);
            return new AuditRow(rs.getLong("id"),rs.getString("action"),payload.actorRole(),rs.getString("outcome"),payload.reasonCode(),rs.getObject("occurred_at",LocalDateTime.class));
        },owner,actionId);
    }

    LocalDateTime now(){return jdbc.queryForObject("SELECT UTC_TIMESTAMP(6)",LocalDateTime.class);}

    private Row row(ResultSet rs,int ignored) throws SQLException {
        int version=rs.getInt("payload_version");var proposal=read(rs.getString("payload_json"),ProposalV1.class);
        protocol.validatePayload(proposal,version);
        String body=rs.getString("result_json"),result=null;
        if(body!=null){if(rs.getInt("result_version")!=1||!sha(body).equals(rs.getString("result_sha256")))throw changed();result=read(body,ResultV1.class).resultJson();validateJson(result);}
        return new Row(rs.getLong("id"),rs.getString("request_id"),rs.getLong("owner_user_id"),rs.getString("run_id"),rs.getString("session_id"),
                rs.getString("resource_id"),rs.getString("request_sha256"),rs.getString("status"),rs.getLong("revision"),rs.getString("error_code"),
                rs.getObject("created_at",LocalDateTime.class),rs.getObject("expires_at",LocalDateTime.class),rs.getObject("confirmation_recorded_at",LocalDateTime.class),proposal,result);
    }

    private void validate(ProposalV1 proposal) {
        if(proposal==null||!Set.of("ASSIGN_QUALITY_TASK","RETRY_DETECTION","CREATE_DETECTION").contains(proposal.operation())
                ||proposal.resourceVersion()==null||proposal.policyVersion()==null||length(proposal.policyVersion())>64
                ||length(proposal.resourceVersion())>64||proposal.callId()!=null&&length(proposal.callId())>160)
            throw new IllegalArgumentException("Unsupported approval proposal payload");
        validateJson(proposal.commandJson());validateJson(proposal.beforeJson());
    }
    private void validateJson(String body){try{if(body==null||json.readTree(body)==null)throw changed();}catch(com.fasterxml.jackson.core.JsonProcessingException error){throw new IllegalArgumentException("Invalid approval JSON",error);}}
    private static int length(String value){return value.codePointCount(0,value.length());}
    private <T>T read(String body,Class<T> type){try{return json.readValue(body,type);}catch(Exception error){throw new IllegalStateException("Approval evidence cannot be decoded",error);}}
    private String write(Object value){try{return json.writeValueAsString(value);}catch(Exception error){throw new IllegalArgumentException("Approval evidence cannot be encoded",error);}}
    private static String sha(String value){try{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8)));}catch(java.security.NoSuchAlgorithmException impossible){throw new IllegalStateException(impossible);}}
    private static IllegalStateException changed(){return new IllegalStateException("Approval evidence changed or is inconsistent");}
}
