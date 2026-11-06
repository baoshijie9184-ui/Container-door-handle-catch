package com.ruanzhu.doorhandle.module.detection.service.detection;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.framework.persistence.JdbcTransactions;
import java.util.Objects;
import org.springframework.jdbc.core.JdbcTemplate;

/** Closed creation protocols. Identities, state, ownership and leases remain indexed relational columns. */
public final class DetectionCreationPersistence {
    public record JobV1(String actorUsername,String actorRole,String proposalId,String previewJson,
                        String bucketName,String sourcePrefix,String manifestSha256) { }
    public record TransferV1(String objectKey,String contentSha256,long byteLength,String contentType,
                             String etag,String objectVersion,String ossRequestId) { }
    public record ReviewV1(String action,String sourceCheckId,int checkedCount,int verifiedCount,
                           String evidenceJson,String evidenceSha256,Long completedRevision) { }
    // Only these fixed projections exist; they are not database views or a legacy SQL translation layer.
    public static final String JOB_COLUMNS = "w.id,SUBSTRING(w.workflow_id,12) AS command_id,w.owner_user_id AS actor_user_id,"
            +value("actorUsername")+" AS actor_username,"+value("actorRole")+" AS actor_role,w.request_id,"
            +value("proposalId")+" AS proposal_id,w.resource_id AS task_id,w.run_id AS dispatch_id,w.session_id,"
            +value("previewJson")+" AS preview_json,w.request_sha256 AS preview_sha256,w.status,"
            +"w.claim_token AS owner_token,w.lease_expires_at AS lease_until,w.error_code AS reason_code,w.revision,"
            +value("bucketName")+" AS bucket_name,"+value("sourcePrefix")+" AS source_prefix,"
            +value("manifestSha256")+" AS manifest_sha256,w.created_at,w.updated_at";
    public static final String TRANSFER_COLUMNS = "w.id,w.resource_id AS command_id,w.resource_revision AS image_index,"
            +"w.run_id AS file_id,"+value("objectKey")+" AS object_key,"+value("contentSha256")+" AS content_sha256,"
            +"CAST(JSON_UNQUOTE(JSON_EXTRACT(w.payload_json,'$.byteLength')) AS SIGNED) AS byte_length,"
            +value("contentType")+" AS content_type,w.status AS state,w.claim_token AS upload_token,"
            +value("etag")+" AS etag,"+value("objectVersion")+" AS object_version,"+value("ossRequestId")+" AS oss_request_id,w.updated_at";
    public static final String REVIEW_COLUMNS = "w.id,SUBSTRING(w.workflow_id,11) AS check_id,w.resource_id AS command_id,"
            +"w.owner_user_id AS actor_user_id,w.request_id,w.resource_revision AS expected_revision,"
            +value("action")+" AS action,"+value("sourceCheckId")+" AS source_check_id,w.status,"
            +"w.claim_token AS worker_token,w.lease_expires_at AS lease_until,"
            +"CAST(JSON_UNQUOTE(JSON_EXTRACT(w.payload_json,'$.checkedCount')) AS SIGNED) AS checked_count,"
            +"CAST(JSON_UNQUOTE(JSON_EXTRACT(w.payload_json,'$.verifiedCount')) AS SIGNED) AS verified_count,"
            +value("evidenceJson")+" AS evidence_json,"+value("evidenceSha256")+" AS evidence_sha256,"
            +"CAST(NULLIF(JSON_UNQUOTE(JSON_EXTRACT(w.payload_json,'$.completedRevision')),'null') AS SIGNED) AS completed_revision,"
            +"w.error_code AS reason_code,w.created_at,w.updated_at";
    private static String value(String field){return "CASE WHEN JSON_TYPE(JSON_EXTRACT(w.payload_json,'$."+field+"'))='NULL' THEN NULL ELSE JSON_UNQUOTE(JSON_EXTRACT(w.payload_json,'$."+field+"')) END";}
    private final JdbcTemplate jdbc;
    private final ObjectMapper json;
    public DetectionCreationPersistence(JdbcTemplate jdbc,ObjectMapper json){
        this.jdbc=Objects.requireNonNull(jdbc);
        this.json=json.copy().setSerializationInclusion(JsonInclude.Include.ALWAYS)
                .enable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES);
    }
    public void validateSchema(){jdbc.queryForList("SELECT kind,workflow_id,owner_user_id,request_id,request_sha256,"
            +"resource_id,resource_revision,run_id,status,revision,claim_token,lease_expires_at,payload_version,payload_json "
            +"FROM workflow_instance WHERE 1=0");}
    public void reserveOwner(long owner){
        JdbcTransactions.requireActive(jdbc);
        jdbc.update("INSERT INTO runtime_state(namespace,owner_id,scope_key,created_at,updated_at) "
                +"VALUES('DETECTION_CREATION_OWNER',?,'',UTC_TIMESTAMP(6),UTC_TIMESTAMP(6)) "
                +"ON DUPLICATE KEY UPDATE owner_id=VALUES(owner_id)",owner);
        lockOwner(owner);
    }
    public void lockOwner(long owner){
        JdbcTransactions.requireActive(jdbc);
        jdbc.queryForObject("SELECT owner_id FROM runtime_state WHERE namespace='DETECTION_CREATION_OWNER' "
                +"AND owner_id=? AND scope_key='' FOR UPDATE",Long.class,owner);
    }
    public void insertJob(String command,long actor,String username,String role,String request,String proposal,
                          String task,String dispatch,String session,String preview,String fingerprint){
        JdbcTransactions.requireActive(jdbc);
        var payload=new JobV1(username,role,proposal,preview,null,null,null);
        jdbc.update("""
                INSERT INTO workflow_instance(workflow_id,kind,idempotency_scope,request_id,request_sha256,
                  owner_user_id,actor_user_id,resource_type,resource_id,run_id,session_id,status,payload_version,payload_json,
                  created_at,updated_at)
                VALUES(CONCAT('det-create:',?),'DETECTION_CREATION',?,?,?,?,?,'DETECTION_TASK',?,?,?,'PREPARING',1,?,
                  UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))
                """,command,"OWNER:"+actor,request,fingerprint,actor,actor,task,dispatch,session,write(payload));
    }
    public void insertTransfer(String command,long owner,int index,String file,String key,String sha,long bytes,String type){
        JdbcTransactions.requireActive(jdbc);
        var payload=new TransferV1(key,sha,bytes,type,null,null,null);
        String scope="DETECTION_CREATION:"+command;
        jdbc.update("""
                INSERT INTO workflow_instance(workflow_id,kind,idempotency_scope,request_id,request_sha256,
                  owner_user_id,actor_user_id,resource_type,resource_id,resource_revision,run_id,status,payload_version,payload_json,
                  created_at,updated_at)
                VALUES(?,'DETECTION_TRANSFER',?,?,?,?,?,'DETECTION_CREATION',?,?,?,'PLANNED',1,?,UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))
                """,DetectionExecutionPersistence.identifier("det-upload:",command+":"+file),scope,file,
                DetectionExecutionPersistence.sha(write(payload)),owner,owner,command,index,file,write(payload));
    }
    public void insertReview(String id,String command,long actor,String request,long revision,String action,String source,String state){
        JdbcTransactions.requireActive(jdbc);
        var payload=new ReviewV1(action,source,0,0,null,null,null);
        String fingerprint=DetectionExecutionPersistence.sha(write(new ReviewRequestV1(command,revision,action,source)));
        jdbc.update("""
                INSERT INTO workflow_instance(workflow_id,kind,idempotency_scope,request_id,request_sha256,
                  owner_user_id,actor_user_id,resource_type,resource_id,resource_revision,status,payload_version,payload_json,
                  created_at,updated_at)
                VALUES(CONCAT('det-check:',?),'DETECTION_TRANSFER_REVIEW',?,?,?,?,?,'DETECTION_CREATION',?,?,?,1,?,
                  UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))
                """,id,"OWNER:"+actor,request,fingerprint,actor,actor,command,revision,state,write(payload));
    }
    private record ReviewRequestV1(String command,long revision,String action,String sourceCheckId) { }
    private String write(Object value){try{return json.writeValueAsString(value);}catch(Exception invalid){throw new IllegalArgumentException("Creation protocol cannot be encoded",invalid);}}
}
