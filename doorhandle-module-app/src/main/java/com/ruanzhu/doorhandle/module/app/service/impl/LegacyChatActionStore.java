package com.ruanzhu.doorhandle.module.app.service.impl;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.framework.persistence.workflow.WorkflowKind;
import com.ruanzhu.doorhandle.framework.persistence.workflow.WorkflowProtocol;
import com.ruanzhu.doorhandle.framework.persistence.workflow.WorkflowProtocols;
import com.ruanzhu.doorhandle.module.app.entity.ChatPendingAction;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.LocalDateTime;
import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.support.TransactionTemplate;

/** The retired chat protocol retains cancellation and original session CASCADE semantics. */
@Repository
public class LegacyChatActionStore {
    public record PendingV1(String actionType,String actionPayload,String errorMessage,String legacyId,
                            String legacySessionId,String legacyCreatedAt,String legacyConfirmedAt,String sourceUtcOffset) { }
    public record TransitionV1(String actionType,String previousStatus,String status,String errorMessage,String previousErrorMessage) { }
    private record Row(long id,long revision,String status,String digest,LocalDateTime created,LocalDateTime confirmed,
                       String actionId,String session,PendingV1 payload) { }
    private static final Set<String> TERMINAL=Set.of("CONFIRMED","COMPLETED","FAILED","CANCELLED","REJECTED","EXPIRED");
    private final JdbcTemplate jdbc;
    private final ObjectMapper json;
    private final TransactionTemplate tx;
    private final WorkflowProtocol<PendingV1> protocol;

    public LegacyChatActionStore(JdbcTemplate jdbc,ObjectMapper mapper,PlatformTransactionManager transactions) {
        this.jdbc=jdbc;json=mapper.copy().setSerializationInclusion(JsonInclude.Include.ALWAYS)
                .enable(DeserializationFeature.FAIL_ON_MISSING_CREATOR_PROPERTIES);
        tx=new TransactionTemplate(transactions);tx.setIsolationLevel(TransactionDefinition.ISOLATION_READ_COMMITTED);
        protocol=new WorkflowProtocol<>(WorkflowKind.LEGACY_CHAT_ACTION,1,PendingV1.class,Set.of("PENDING"),TERMINAL,
                Map.of("PENDING",Set.of("EXECUTING","CONFIRMED","FAILED","CANCELLED","REJECTED","EXPIRED"),
                        "EXECUTING",Set.of("CONFIRMED","COMPLETED","FAILED","UNKNOWN","NEEDS_REVIEW"),
                        "UNKNOWN",Set.of("CONFIRMED","COMPLETED","FAILED","CANCELLED"),
                        "NEEDS_REVIEW",Set.of("CONFIRMED","COMPLETED","FAILED","CANCELLED")),this::validate,false);
        WorkflowProtocols.defaults().with(protocol).require(WorkflowKind.LEGACY_CHAT_ACTION);
    }

    public ChatPendingAction insert(long user,ChatPendingAction value) {
        if(value==null||value.getActionId()==null||value.getActionId().isEmpty()||length(value.getActionId())>64)
            throw new IllegalArgumentException("Invalid legacy chat action identity");
        var payload=new PendingV1(value.getActionType(),value.getActionPayloadJson(),null,null,null,null,null,null);
        protocol.validatePayload(payload,1);protocol.requireInitial("PENDING");
        return tx.execute(status->{
            String session=lockSession(user,value.getSessionId());LocalDateTime now=now();String workflow=UUID.randomUUID().toString();
            String body=write(payload),digest=sha(write(List.of(payload.actionType(),payload.actionPayload())));
            jdbc.update("""
                    INSERT INTO workflow_instance(workflow_id,kind,idempotency_scope,request_id,request_sha256,owner_user_id,
                      actor_user_id,resource_type,resource_id,chat_action_session_id,status,revision,payload_version,payload_json,created_at,updated_at)
                    VALUES(?,'LEGACY_CHAT_ACTION','LEGACY_CHAT_ACTION',?,?,?,?,'CHAT_ACTION',?,?,'PENDING',0,1,?,?,?)
                    """,workflow,value.getActionId(),digest,user,user,value.getActionId(),session,body,now,now);
            var saved=required(session,value.getActionId(),true,null);
            audit(user,saved,"CREATED",null,"PENDING",null,null);
            return dto(saved);
        });
    }

    public ChatPendingAction get(long user,String session,String actionId) {
        return tx.execute(status->{String current=lockSession(user,session);return dto(required(current,actionId,false,null));});
    }

    /** Used only by compatibility callers; the public confirm endpoint still refuses legacy execution. */
    public void mark(long user,String session,String actionId,String target) {
        if(!transition(user,session,actionId,"PENDING",target,null,true))throw new BusinessException(409,"此动作已处理");
    }

    public boolean transition(long user,String session,String actionId,String expected,String target,String error) {
        return transition(user,session,actionId,expected,target,error,false);
    }

    private boolean transition(long user,String session,String actionId,String expected,String target,String error,boolean markConfirmed) {
        if(expected==null||target==null||error!=null&&length(error)>500)throw new IllegalArgumentException("Invalid legacy action transition");
        protocol.requireTransition(expected,target);
        return Boolean.TRUE.equals(tx.execute(transaction->{
            String current=lockSession(user,session);
            // Keep the source status/action-id unicode_ci comparison, while the live session is the exact current FK.
            Row row=find(current,actionId,true,expected);if(row==null)return false;
            LocalDateTime now=now(),confirmed=markConfirmed||"EXECUTING".equals(target)?now:row.confirmed();
            var old=row.payload();var payload=new PendingV1(old.actionType(),old.actionPayload(),error,old.legacyId(),old.legacySessionId(),old.legacyCreatedAt(),old.legacyConfirmedAt(),old.sourceUtcOffset());
            int changed=jdbc.update("UPDATE workflow_instance SET status=?,revision=revision+1,payload_json=?,confirmation_recorded_at=?,updated_at=?,finished_at=? "
                            +"WHERE kind='LEGACY_CHAT_ACTION' AND id=? AND revision=? AND status COLLATE utf8mb4_unicode_ci=?",
                    target,write(payload),confirmed,now,TERMINAL.contains(target)?now:null,row.id(),row.revision(),expected);
            if(changed!=1)throw new BusinessException(409,"此动作已处理");
            audit(user,row,"STATE_CHANGED",row.status(),target,error,old.errorMessage());return true;
        }));
    }

    /** Session deletion itself cascades these rows; the caller need not invent an audit for old removals. */
    public void deleteSession(long user,String session) {
        tx.executeWithoutResult(status->{String current=lockSession(user,session);jdbc.update("DELETE FROM workflow_instance WHERE kind='LEGACY_CHAT_ACTION' AND chat_action_session_id=?",current);});
    }

    private String lockSession(long user,String session) {
        if(user<=0||session==null)throw new SecurityException("会话不属于当前账号");
        var rows=jdbc.queryForList("SELECT session_id,user_id FROM chat_session WHERE session_id=? FOR UPDATE",session);
        if(rows.size()!=1||((Number)rows.get(0).get("user_id")).longValue()!=user)throw new SecurityException("会话不属于当前账号");
        return (String)rows.get(0).get("session_id");
    }

    private Row required(String session,String action,boolean lock,String expected) {
        var row=find(session,action,lock,expected);if(row==null)throw new BusinessException(404,"待确认动作不存在");return row;
    }
    private Row find(String session,String action,boolean lock,String expected) {
        var args=new ArrayList<Object>(Arrays.asList(session,action));String sql="SELECT * FROM workflow_instance WHERE kind='LEGACY_CHAT_ACTION' AND chat_action_session_id=? AND chat_action_id=?";
        if(expected!=null){sql+=" AND status COLLATE utf8mb4_unicode_ci=?";args.add(expected);}
        if(lock)sql+=" FOR UPDATE";
        var rows=jdbc.query(sql,this::row,args.toArray());return rows.isEmpty()?null:rows.get(0);
    }

    private Row row(ResultSet rs,int ignored) throws SQLException {
        var payload=read(rs.getString("payload_json"));protocol.validatePayload(payload,rs.getInt("payload_version"));
        return new Row(rs.getLong("id"),rs.getLong("revision"),rs.getString("status"),rs.getString("request_sha256"),
                rs.getObject("created_at",LocalDateTime.class),rs.getObject("confirmation_recorded_at",LocalDateTime.class),
                rs.getString("request_id"),rs.getString("chat_action_session_id"),payload);
    }
    private ChatPendingAction dto(Row row) {
        var value=new ChatPendingAction();value.setId(row.id());value.setActionId(row.actionId());value.setSessionId(row.session());
        value.setActionType(row.payload().actionType());value.setActionPayloadJson(row.payload().actionPayload());value.setStatus(row.status());
        value.setCreatedAt(display(row.created()));value.setConfirmedAt(display(row.confirmed()));value.setErrorMessage(row.payload().errorMessage());return value;
    }
    private void audit(long owner,Row row,String action,String previous,String state,String error,String oldError) {
        var body=new TransitionV1(row.payload().actionType(),previous,state,error,oldError);
        jdbc.update("""
                INSERT INTO audit_event(event_id,kind,owner_user_id,actor_user_id,resource_type,resource_id,session_id,
                  action,revision,content_sha256,outcome,payload_version,payload_json)
                VALUES(?,'LEGACY_CHAT_ACTION',?,?,'LEGACY_CHAT_ACTION',?,?,?,?,?,?,1,?)
                """,UUID.randomUUID().toString(),owner,owner,row.actionId(),row.session(),action,
                "CREATED".equals(action)?row.revision():row.revision()+1,row.digest(),state,write(body));
    }

    private void validate(PendingV1 value) {
        // actionPayload was LONGTEXT, not a JSON column. Even invalid JSON is immutable historical evidence.
        if(value==null||value.actionType()==null||length(value.actionType())>64||value.actionPayload()==null
                ||value.errorMessage()!=null&&length(value.errorMessage())>500)throw new IllegalArgumentException("Invalid retained chat action payload");
    }
    private PendingV1 read(String value){try{return json.readValue(value,PendingV1.class);}catch(Exception error){throw new IllegalStateException("旧聊天动作记录无法读取",error);}}
    private String write(Object value){try{return json.writeValueAsString(value);}catch(Exception error){throw new IllegalArgumentException("Cannot encode legacy action evidence",error);}}
    private LocalDateTime now(){return jdbc.queryForObject("SELECT UTC_TIMESTAMP(6)",LocalDateTime.class);}
    private static LocalDateTime display(LocalDateTime utc){return utc==null?null:utc.plusHours(8);}
    private static int length(String value){return value.codePointCount(0,value.length());}
    private static String sha(String text){try{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(text.getBytes(StandardCharsets.UTF_8)));}catch(java.security.NoSuchAlgorithmException impossible){throw new IllegalStateException(impossible);}}
}
