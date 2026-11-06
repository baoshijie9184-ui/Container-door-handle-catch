package com.ruanzhu.doorhandle.module.detection.service.detection;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.framework.persistence.JdbcTransactions;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.LocalDateTime;
import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;

/** Detection command, broker delivery and permanent worker-fence protocols in the compact schema. */
public final class DetectionExecutionPersistence {
    public static final String COMMAND = "DETECTION_COMMAND";
    public static final String DISPATCH = "DETECTION_DISPATCH";
    public static final String WORKER = "DETECTION_WORKER";
    /** Original external identifiers and bytes remain distinct from the shared row cursor. */
    public record CommandV1(String commandId, String operation, String proposalId) { }
    public record DispatchV1(String eventJson, String actorRequestId) { }
    public record Delivery(long id, String token, String payload, String fingerprint,
                           String taskId, String dispatchId, String eventId, int attempts) { }

    private final JdbcTemplate jdbc;
    private final ObjectMapper json;
    public DetectionExecutionPersistence(JdbcTemplate jdbc, ObjectMapper json) {
        this.jdbc = Objects.requireNonNull(jdbc);
        this.json = json.copy().setSerializationInclusion(JsonInclude.Include.ALWAYS)
                .enable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES);
    }
    public void validateSchema() {
        jdbc.queryForList("SELECT workflow_id,kind,idempotency_scope,request_id,request_sha256,owner_user_id,"
                + "resource_id,run_id,status,claim_token,fence,lease_expires_at,attempts,payload_version,payload_json,"
                + "result_version,result_json,result_sha256,created_at,updated_at FROM workflow_instance WHERE 1=0");
    }
    public List<Map<String,Object>> command(long owner, String request) {
        var rows = jdbc.queryForList("SELECT * FROM workflow_instance WHERE kind='DETECTION_COMMAND' "
                + "AND idempotency_scope=? AND owner_user_id=? AND request_id=?", "OWNER:"+owner, owner, request);
        var result = new ArrayList<Map<String,Object>>();
        for (var row : rows) {
            requireVersion(row); var payload = read((String)row.get("payload_json"),CommandV1.class);
            validate(payload);
            if (!"DETECTION_TASK".equals(row.get("resource_type")) || !"COMPLETED".equals(row.get("status"))
                    || !identifier("det-cmd:", payload.commandId()).equals(row.get("workflow_id"))
                    || !(row.get("result_json") instanceof String body)
                    || !sha(body).equals(row.get("result_sha256")))
                throw new IllegalStateException("Stored detection command identity or receipt differs");
            var value = new LinkedHashMap<String,Object>();
            value.put("payload_sha256", row.get("request_sha256")); value.put("command_id",payload.commandId());
            value.put("command_type",payload.operation()); value.put("task_id",row.get("resource_id"));
            value.put("dispatch_id",row.get("run_id")); value.put("result_json",body); result.add(value);
        }
        return result;
    }
    public void saveCommand(String command, long actor, String request, String operation, String fingerprint,
                            String proposal, String task, String dispatch, String result) {
        JdbcTransactions.requireActive(jdbc);
        var payload = new CommandV1(command,operation,proposal); validate(payload);
        jdbc.update("""
                INSERT INTO workflow_instance(workflow_id,kind,idempotency_scope,request_id,request_sha256,
                  owner_user_id,actor_user_id,resource_type,resource_id,run_id,status,payload_version,payload_json,
                  result_version,result_json,result_sha256,created_at,updated_at,finished_at)
                VALUES(?,'DETECTION_COMMAND',?,?,?,?,?,'DETECTION_TASK',?,?,'COMPLETED',1,?,1,?,?,
                  UTC_TIMESTAMP(6),UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))
                """,identifier("det-cmd:",command),"OWNER:"+actor,request,fingerprint,actor,actor,task,dispatch,
                write(payload),result,sha(result));
    }
    public List<Map<String,Object>> dispatch(String task,String dispatch) {
        var rows=jdbc.queryForList("SELECT request_id AS event_id,request_sha256 AS payload_sha256 FROM workflow_instance "
                + "WHERE kind='DETECTION_DISPATCH' AND resource_id=? AND run_id=?",task,dispatch);
        if(rows.size()>1)throw new IllegalStateException("Detection dispatch identity is not unique");
        return rows;
    }
    public List<Map<String,Object>> dispatch(String task,String dispatch,long actor,String request) {
        return jdbc.queryForList("SELECT request_id AS event_id FROM workflow_instance WHERE kind='DETECTION_DISPATCH' "
                + "AND resource_id=? AND run_id=? AND owner_user_id=? "
                + "AND JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.actorRequestId'))=?",task,dispatch,actor,request);
    }
    public int dispatchCount(String task,String dispatch) {
        return jdbc.queryForObject("SELECT COUNT(*) FROM workflow_instance WHERE kind='DETECTION_DISPATCH' "
                + "AND resource_id=? AND run_id=?",Integer.class,task,dispatch);
    }
    public void enqueue(String event,String task,String dispatch,String body,String fingerprint,long actor,String request) {
        JdbcTransactions.requireActive(jdbc);
        var payload=new DispatchV1(body,request);validate(payload);
        jdbc.update("""
                INSERT INTO workflow_instance(workflow_id,kind,idempotency_scope,request_id,request_sha256,
                  owner_user_id,actor_user_id,resource_type,resource_id,run_id,status,next_attempt_at,
                  payload_version,payload_json,created_at,updated_at)
                VALUES(?,'DETECTION_DISPATCH','DETECTION_DISPATCH',?,?,?,?,'DETECTION_TASK',?,?,'PENDING',
                  UTC_TIMESTAMP(6),1,?,UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))
                """,identifier("det-out:",event),event,fingerprint,actor,actor,task,dispatch,write(payload));
    }
    /** Reclaiming a broker delivery only resends the exact same immutable event. */
    public Delivery claimDelivery() {
        JdbcTransactions.requireActive(jdbc);
        var rows=jdbc.queryForList("SELECT * FROM workflow_instance WHERE kind='DETECTION_DISPATCH' "
                + "AND ((status='PENDING' AND next_attempt_at<=UTC_TIMESTAMP(6)) "
                + "OR (status='SENDING' AND lease_expires_at<UTC_TIMESTAMP(6))) ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED");
        if(rows.isEmpty())return null;
        var row=rows.get(0);requireVersion(row);var payload=read((String)row.get("payload_json"),DispatchV1.class);validate(payload);
        String event=(String)row.get("request_id");
        if(!identifier("det-out:",event).equals(row.get("workflow_id"))||!"DETECTION_TASK".equals(row.get("resource_type")))
            throw new IllegalStateException("Stored detection delivery identity differs");
        long id=((Number)row.get("id")).longValue();String token=UUID.randomUUID().toString();
        int attempts=((Number)row.get("attempts")).intValue();
        if(attempts==Integer.MAX_VALUE)throw new IllegalStateException("Detection delivery attempts exhausted");
        jdbc.update("UPDATE workflow_instance SET status='SENDING',attempts=attempts+1,claim_token=?,"
                + "lease_expires_at=DATE_ADD(UTC_TIMESTAMP(6),INTERVAL 2 MINUTE),fence=fence+1,revision=revision+1,"
                + "updated_at=UTC_TIMESTAMP(6) WHERE kind='DETECTION_DISPATCH' AND id=?",token,id);
        return new Delivery(id,token,payload.eventJson(),(String)row.get("request_sha256"),
                (String)row.get("resource_id"),(String)row.get("run_id"),event,attempts+1);
    }
    public void deliveryReview(Delivery claim) { finishDelivery(claim,"NEEDS_REVIEW","INVALID_STORED_EVENT",null); }
    public void deliverySent(Delivery claim) { finishDelivery(claim,"SENT",null,null); }
    public void deliveryRetry(Delivery claim,LocalDateTime at) { finishDelivery(claim,"PENDING","ACK_UNCONFIRMED",at); }
    private void finishDelivery(Delivery claim,String state,String error,LocalDateTime next) {
        jdbc.update("UPDATE workflow_instance SET status=?,error_code=?,next_attempt_at=COALESCE(?,next_attempt_at),"
                + "claim_token=NULL,lease_expires_at=NULL,revision=revision+1,updated_at=UTC_TIMESTAMP(6),"
                + "finished_at=CASE WHEN ?='SENT' THEN UTC_TIMESTAMP(6) ELSE NULL END "
                + "WHERE kind='DETECTION_DISPATCH' AND id=? AND status='SENDING' AND claim_token=?",
                state,error,next,state,claim.id(),claim.token());
    }
    public LocalDateTime now() { return jdbc.queryForObject("SELECT UTC_TIMESTAMP(6)",LocalDateTime.class); }
    public List<Map<String,Object>> workerReceipt(String task,String dispatch) {
        var rows=jdbc.queryForList("SELECT status,result_json,result_sha256,payload_version,payload_json FROM workflow_instance "
                + "WHERE kind='DETECTION_WORKER' AND resource_id=? AND run_id=?",task,dispatch);
        if(rows.size()>1)throw new IllegalStateException("Detection worker fence identity is not unique");
        for(var row:rows){requireVersion(row);try{
            var payload=json.readTree((String)row.get("payload_json"));
            if(!payload.isObject()||payload.size()!=1||!payload.path("schemaVersion").isIntegralNumber()
                    ||payload.path("schemaVersion").asInt()!=1)throw new IllegalStateException();
        }catch(Exception invalid){throw new IllegalStateException("Stored detection worker protocol is invalid");}}
        return rows;
    }
    private static void validate(CommandV1 p) {
        token(p.commandId(),128);token(p.operation(),24);if(p.proposalId()!=null)token(p.proposalId(),128);
        if(!Set.of("RETRY","CREATE").contains(p.operation()))throw new IllegalArgumentException("Unsupported detection command");
    }
    private static void validate(DispatchV1 p) {
        token(p.actorRequestId(),128);
        if(p.eventJson()==null||p.eventJson().isBlank()||p.eventJson().getBytes(StandardCharsets.UTF_8).length>16_777_215)
            throw new IllegalArgumentException("Detection event exceeds original storage bound");
    }
    private static void token(String value,int max) {
        if(value==null||!value.matches("[A-Za-z0-9_-]{1,"+max+"}"))throw new IllegalArgumentException("Invalid detection identity");
    }
    private static void requireVersion(Map<String,Object> row) {
        if(!(row.get("payload_version") instanceof Number version)||version.intValue()!=1)
            throw new IllegalStateException("Unsupported detection storage protocol");
    }
    private <P>P read(String value,Class<P> type){try{return json.readValue(value,type);}catch(Exception bad){throw new IllegalStateException("Stored detection payload is invalid",bad);}}
    private String write(Object value){try{return json.writeValueAsString(value);}catch(Exception bad){throw new IllegalArgumentException("Detection payload cannot be encoded",bad);}}
    public static String identifier(String prefix,String original){return prefix+sha(original).substring(0,48);}
    public static String sha(String value){try{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8)));}catch(Exception impossible){throw new IllegalStateException(impossible);}}
}
