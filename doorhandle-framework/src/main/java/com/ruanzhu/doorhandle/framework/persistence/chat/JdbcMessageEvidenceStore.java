package com.ruanzhu.doorhandle.framework.persistence.chat;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.framework.persistence.JdbcTransactions;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;

/** Evidence and its current projection commit together. Evidence never references a deleting chat/user/run parent. */
public final class JdbcMessageEvidenceStore {
    private static final DateTimeFormatter SOURCE_TIME=DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss.SSSSSS");
    private final JdbcTemplate jdbc;private final ObjectMapper json;
    public JdbcMessageEvidenceStore(JdbcTemplate jdbc,ObjectMapper json){
        this.jdbc=jdbc;
        // Typed evidence requires every declared field, including a null legacyId on new writes.
        // Keep this storage protocol independent of the application's HTTP NON_NULL policy.
        this.json=json.copy().setSerializationInclusion(JsonInclude.Include.ALWAYS);
    }
    public void validateSchema(){jdbc.queryForList("SELECT execution_evidence_id,snapshot_evidence_id,context_evidence_id FROM chat_message WHERE 1=0");jdbc.queryForList("SELECT id,kind,owner_user_id,session_id,message_id,run_id,payload_version,payload_json FROM audit_event WHERE 1=0");}

    /** Invalid/stale replies are ignored; a committed original binding is never reassigned. */
    public boolean bindExecution(long owner,String session,long message,String run) {
        JdbcTransactions.requireActive(jdbc);
        var current=lockMessage(owner,session,message,true);if(current==null)return false;
        if(!Set.of("TEXT","AGENT_CARDS").contains(Objects.toString(current.get("message_type"),"")))return false;
        Long pointer=number(current.get("execution_evidence_id"));
        if(pointer!=null){var event=event(pointer,MessageEvidence.EXECUTION,owner,message);verifyExecution(event);return run.equals(event.get("run_id"));}
        var eligible=jdbc.queryForList("SELECT run_id FROM agent_run WHERE user_id=? AND session_id=? AND run_id=? AND entry_point IN ('CHAT','AGUI') AND status IN ('COMPLETED','INTERRUPTED') FOR SHARE",owner,session,run);
        if(eligible.isEmpty())return false;
        // Global original message/run identities remain occupied even after their projection is deleted.
        var previous=jdbc.queryForList("SELECT id FROM audit_event WHERE execution_message_id=? OR execution_run_id=? FOR SHARE",message,run);
        if(!previous.isEmpty())return false;
        LocalDateTime now=now();var payload=new MessageEvidence.ExecutionV1(null,SOURCE_TIME.format(now),"+00:00");
        long evidence=append(MessageEvidence.EXECUTION,owner,session,message,run,hash(write(payload)),now,payload);
        if(jdbc.update("UPDATE chat_message SET execution_evidence_id=?,execution_owner_user_id=?,execution_run_id=?,execution_created_at=? WHERE id=? AND execution_evidence_id IS NULL",evidence,owner,run,now,message)!=1)
            throw new IllegalStateException("Message execution projection changed while locked");
        return true;
    }

    public boolean saveSnapshot(long owner,String session,long message,String body) {
        JdbcTransactions.requireActive(jdbc);validateJson(body);
        var current=lockMessage(owner,session,message,true);if(current==null)throw new SecurityException("附件切点消息不属于当前账号");
        Long pointer=number(current.get("snapshot_evidence_id"));
        if(pointer!=null){var prior=event(pointer,MessageEvidence.SNAPSHOT,owner,message);String previous=read(prior,MessageEvidence.WorkspaceSnapshotV1.class).snapshotJson();verifyBody(prior,previous);if(!body.equals(previous))throw conflict();return false;}
        LocalDateTime now=now();long evidence=append(MessageEvidence.SNAPSHOT,owner,session,message,null,hash(body),now,new MessageEvidence.WorkspaceSnapshotV1(null,body,SOURCE_TIME.format(now),"+00:00"));
        if(jdbc.update("UPDATE chat_message SET snapshot_evidence_id=?,snapshot_owner_user_id=?,workspace_snapshot_json=?,workspace_snapshot_sha256=?,workspace_snapshot_created_at=? WHERE id=? AND snapshot_evidence_id IS NULL",evidence,owner,body,hash(body),now,message)!=1)throw conflict();
        return true;
    }

    public boolean saveSources(long owner,String session,long message,String body) {
        JdbcTransactions.requireActive(jdbc);validateJson(body);
        var current=lockMessage(owner,session,message,false);if(current==null)throw new SecurityException("历史轮次消息不属于当前账号");
        Long pointer=number(current.get("context_evidence_id"));
        if(pointer!=null){var prior=event(pointer,MessageEvidence.SOURCES,owner,message);String previous=read(prior,MessageEvidence.ContextSourcesV1.class).sourcesJson();verifyBody(prior,previous);if(!body.equals(previous))throw conflict();return false;}
        long evidence=append(MessageEvidence.SOURCES,owner,session,message,null,hash(body),now(),new MessageEvidence.ContextSourcesV1(body));
        if(jdbc.update("UPDATE chat_message SET context_evidence_id=?,context_owner_user_id=?,context_sources_json=?,context_sources_sha256=? WHERE id=? AND context_evidence_id IS NULL",evidence,owner,body,hash(body),message)!=1)throw conflict();
        return true;
    }

    public String loadSnapshot(long owner,String session,long message){var event=currentEvidence(owner,session,message,"snapshot_evidence_id",MessageEvidence.SNAPSHOT);if(event==null)return null;var payload=read(event,MessageEvidence.WorkspaceSnapshotV1.class);if(payload.createdAtSource()==null||payload.sourceUtcOffset()==null)throw conflict();String body=payload.snapshotJson();verifyBody(event,body);return body;}
    public String loadSources(long owner,String session,long message){var event=currentEvidence(owner,session,message,"context_evidence_id",MessageEvidence.SOURCES);if(event==null)return null;String body=read(event,MessageEvidence.ContextSourcesV1.class).sourcesJson();verifyBody(event,body);return body;}

    public Map<Long,String> executionLinks(long owner,String session,List<Long> messages) {
        if(messages.isEmpty())return Map.of();if(messages.size()>200)throw new IllegalArgumentException("Message evidence batch exceeds 200");
        var args=new ArrayList<Object>(List.of(owner,session));args.addAll(messages);
        var rows=jdbc.queryForList("SELECT e.*,m.id AS current_message FROM chat_message m JOIN chat_session s ON s.session_id=m.session_id JOIN audit_event e ON e.id=m.execution_evidence_id AND e.owner_user_id=m.execution_owner_user_id WHERE s.user_id=? AND m.session_id=? AND m.role='assistant' AND m.message_type IN ('TEXT','AGENT_CARDS') AND m.id IN ("+String.join(",",Collections.nCopies(messages.size(),"?"))+")",args.toArray());
        var result=new HashMap<Long,String>();
        for(var row:rows){long message=((Number)row.get("current_message")).longValue();verifyEnvelope(row,MessageEvidence.EXECUTION,owner,message);verifyExecution(row);result.put(message,(String)row.get("run_id"));}
        return result;
    }

    private Map<String,Object> lockMessage(long owner,String session,long message,boolean assistant) {
        if(owner<=0||message<=0||session==null||session.isBlank()||session.length()>128)throw new IllegalArgumentException("Invalid current message identity");
        var rows=jdbc.queryForList("SELECT m.execution_evidence_id,m.snapshot_evidence_id,m.context_evidence_id,m.message_type FROM chat_message m JOIN chat_session s ON s.session_id=m.session_id WHERE m.id=? AND m.session_id=? AND s.user_id=?"+(assistant?" AND m.role='assistant'":"")+" FOR UPDATE",message,session,owner);
        return rows.isEmpty()?null:rows.get(0);
    }
    private Map<String,Object> currentEvidence(long owner,String session,long message,String pointer,String kind) {
        var rows=jdbc.queryForList("SELECT e.* FROM chat_message m JOIN chat_session s ON s.session_id=m.session_id JOIN audit_event e ON e.id=m."+pointer+" WHERE s.user_id=? AND m.session_id=? AND m.id=?",owner,session,message);
        if(rows.isEmpty())return null;var event=rows.get(0);verifyEnvelope(event,kind,owner,message);return event;
    }
    private Map<String,Object> event(long id,String kind,long owner,long message){var rows=jdbc.queryForList("SELECT * FROM audit_event WHERE id=? FOR SHARE",id);if(rows.size()!=1)throw conflict();var event=rows.get(0);verifyEnvelope(event,kind,owner,message);return event;}
    private void verifyEnvelope(Map<String,Object> event,String kind,long owner,long message) {
        if(!kind.equals(event.get("kind"))||!Objects.equals(number(event.get("owner_user_id")),owner)||!Objects.equals(number(event.get("message_id")),message)
                ||!"CHAT_MESSAGE".equals(event.get("resource_type"))||!Long.toString(message).equals(event.get("resource_id"))||!Objects.equals(number(event.get("payload_version")),1L)
                ||event.get("actor_user_id")!=null||!"RECORDED".equals(event.get("action"))||event.get("session_id")==null
                ||(MessageEvidence.EXECUTION.equals(kind)?event.get("run_id")==null:event.get("run_id")!=null))throw conflict();
    }
    private long append(String kind,long owner,String session,long message,String run,String digest,LocalDateTime time,Object payload) {
        if(!((MessageEvidence.EXECUTION.equals(kind)&&payload instanceof MessageEvidence.ExecutionV1)
                ||(MessageEvidence.SNAPSHOT.equals(kind)&&payload instanceof MessageEvidence.WorkspaceSnapshotV1)
                ||(MessageEvidence.SOURCES.equals(kind)&&payload instanceof MessageEvidence.ContextSourcesV1)))throw new IllegalArgumentException("Unregistered message evidence payload");
        String event=UUID.randomUUID().toString();
        jdbc.update("INSERT INTO audit_event(event_id,kind,owner_user_id,resource_type,resource_id,session_id,message_id,run_id,action,content_sha256,occurred_at,payload_version,payload_json) VALUES(?,?,?,'CHAT_MESSAGE',?,?,?,?,'RECORDED',?,?,1,?)",event,kind,owner,Long.toString(message),session,message,run,digest,time,write(payload));
        return jdbc.queryForObject("SELECT id FROM audit_event WHERE event_id=?",Long.class,event);
    }
    private <T> T read(Map<String,Object> event,Class<T> type){try{return json.readerFor(type).with(com.fasterxml.jackson.databind.DeserializationFeature.FAIL_ON_MISSING_CREATOR_PROPERTIES).readValue((String)event.get("payload_json"));}catch(JsonProcessingException invalid){throw new IllegalStateException("Message evidence payload is unreadable",invalid);}}
    private void verifyExecution(Map<String,Object> event){var payload=read(event,MessageEvidence.ExecutionV1.class);if(payload.createdAtSource()==null||payload.sourceUtcOffset()==null)throw conflict();verifyBody(event,(String)event.get("payload_json"));}
    private void validateJson(String body){try{if(body==null||json.readTree(body)==null)throw conflict();}catch(JsonProcessingException invalid){throw new IllegalArgumentException("Invalid message evidence JSON",invalid);}}
    private void verifyBody(Map<String,Object> event,String body){if(body==null||!(event.get("content_sha256") instanceof String digest)||!hash(body).equalsIgnoreCase(digest))throw conflict();}
    private String write(Object value){try{return json.writeValueAsString(value);}catch(JsonProcessingException invalid){throw new IllegalArgumentException("Cannot encode message evidence",invalid);}}
    private LocalDateTime now(){return jdbc.queryForObject("SELECT UTC_TIMESTAMP(6)",LocalDateTime.class);}
    private static Long number(Object value){return value==null?null:((Number)value).longValue();}
    private static IllegalStateException conflict(){return new IllegalStateException("Message evidence identity or content conflicts with its retained receipt");}
    private static String hash(String body){try{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(body.getBytes(StandardCharsets.UTF_8)));}catch(java.security.NoSuchAlgorithmException impossible){throw new IllegalStateException(impossible);}}
}
