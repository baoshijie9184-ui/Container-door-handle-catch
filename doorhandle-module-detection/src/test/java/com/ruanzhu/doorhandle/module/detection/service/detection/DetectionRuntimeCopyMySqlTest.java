package com.ruanzhu.doorhandle.module.detection.service.detection;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.module.detection.support.DetectionRuntimeCopyMySqlFixture;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.junit.jupiter.api.parallel.Execution;
import org.junit.jupiter.api.parallel.ExecutionMode;
import org.springframework.jdbc.core.JdbcTemplate;
import java.util.Map;
import static org.assertj.core.api.Assertions.*;

/** Executes the original seven-table copy and every-column comparison against real compact MySQL DDL on ECS. */
@EnabledIfSystemProperty(named="doorhandle.detection.runtime.copy.source.config",matches=".+")
@Execution(ExecutionMode.SAME_THREAD)
class DetectionRuntimeCopyMySqlTest {
    static final String COMMAND="12345678-1234-1234-1234-123456789abc";
    static final String FILE="23456789-1234-1234-1234-123456789abc";
    static final String CHECK="34567890-1234-1234-1234-123456789abc";
    static final String ORPHAN="45678901-1234-1234-1234-123456789abc";
    static final String PREVIEW=" { \"source\": [1, null, \"旧原文\"], \"threshold\": 0.5000 } ";
    static final String EVIDENCE=" [ { \"status\": \"VERIFIED\", \"label\": \"原图\" } ] ";
    static final String WALL="2021-02-03 04:05:06.123456";
    DetectionRuntimeCopyMySqlFixture fixture;JdbcTemplate source,target;
    @BeforeEach void setup() throws Exception {fixture=new DetectionRuntimeCopyMySqlFixture();source=fixture.source();target=fixture.target();seed();}
    @AfterEach void close() throws Exception {if(fixture!=null)fixture.close();}

    @Test void preservesAllNinetyTwoSourceColumnsOriginalBytesNullTimesAndPermanentFences() throws Exception {
        long high=source.queryForObject("SELECT auto_increment FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name='detection_creation_object'",Long.class);
        fixture.copy();
        assertThat(target.queryForObject("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE()",Integer.class)).isEqualTo(29);
        assertThat(target.queryForObject("SELECT COUNT(*) FROM workflow_instance WHERE kind LIKE 'DETECTION_%'",Integer.class)).isEqualTo(8);
        assertThat(target.queryForObject("SELECT created_at FROM runtime_state WHERE namespace='DETECTION_CREATION_OWNER'",String.class)).isNull();
        assertThat(target.queryForObject("SELECT updated_at FROM runtime_state WHERE namespace='DETECTION_CREATION_OWNER'",String.class)).isNull();
        var job=target.queryForMap("SELECT "+DetectionCreationPersistence.JOB_COLUMNS+" FROM workflow_instance w WHERE w.kind='DETECTION_CREATION'");
        assertThat(job.get("preview_json")).isEqualTo(PREVIEW);assertThat(job.get("actor_username")).isEqualTo("null");
        assertThat(target.queryForObject("SELECT DATE_FORMAT(created_at,'%Y-%m-%d %H:%i:%s.%f') FROM workflow_instance WHERE kind='DETECTION_CREATION'",String.class)).isEqualTo("2021-02-02 20:05:06.123456");
        var orphan=target.queryForMap("SELECT owner_user_id,actor_user_id,claim_token,lease_expires_at,created_at,legacy_key FROM workflow_instance WHERE kind='DETECTION_TRANSFER' AND resource_id=?",ORPHAN);
        assertThat(((Number)orphan.get("owner_user_id")).longValue()).isZero();assertThat(orphan.get("actor_user_id")).isNull();
        assertThat(orphan.get("claim_token")).isEqualTo("orphan-upload-owner");assertThat(orphan.get("lease_expires_at")).isNull();assertThat(orphan.get("created_at")).isNull();
        assertThat(target.queryForObject("SELECT legacy_key FROM workflow_instance WHERE kind='DETECTION_TRANSFER' AND resource_id=?",String.class,COMMAND)).isEqualTo("9007199254740993");
        assertThat(target.queryForObject("SELECT JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.evidenceJson')) FROM workflow_instance WHERE kind='DETECTION_TRANSFER_REVIEW'",String.class)).isEqualTo(EVIDENCE);
        assertThat(target.queryForObject("SELECT updated_at FROM workflow_instance WHERE kind='DETECTION_COMMAND'",String.class)).isNull();
        assertThat(target.queryForObject("SELECT finished_at FROM workflow_instance WHERE kind='DETECTION_COMMAND'",String.class)).isNull();
        assertThat(target.queryForObject("SELECT claim_token FROM workflow_instance WHERE kind='DETECTION_WORKER' AND resource_id='task-running'",String.class)).isEqualTo("worker-running-owner");
        assertThat(target.queryForObject("SELECT lease_expires_at FROM workflow_instance WHERE kind='DETECTION_WORKER' AND resource_id='task-running'",String.class)).isNull();
        assertThat(source.queryForObject("SELECT auto_increment FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name='detection_creation_object'",Long.class)).isEqualTo(high);
    }
    @Test void unknownSourceColumnStopsBeforeCopyInsteadOfIgnoringData() throws Exception {
        source.execute("ALTER TABLE detection_creation_job ADD COLUMN unreviewed VARCHAR(20) NULL");
        assertThatThrownBy(fixture::copy).isInstanceOf(Exception.class);assertTargetEmpty();
    }
    @Test void badSourceDigestRollsBackOwnerAndAllWorkflowWrites() throws Exception {
        source.update("UPDATE detection_creation_job SET preview_sha256=?","0".repeat(64));
        assertThatThrownBy(fixture::copy).isInstanceOf(Exception.class);assertTargetEmpty();
        assertThat(source.queryForObject("SELECT COUNT(*) FROM detection_creation_job",Integer.class)).isEqualTo(1);
    }
    @Test void repeatedCopyFailsClosedAndRetainsThePreviouslyCopiedFacts() throws Exception {
        fixture.copy();assertThatThrownBy(fixture::copy).isInstanceOf(Exception.class);
        assertThat(target.queryForObject("SELECT COUNT(*) FROM workflow_instance WHERE kind LIKE 'DETECTION_%'",Integer.class)).isEqualTo(8);
    }
    @Test void oldCancelledLeaseWithNoOwnerRemainsEvidenceRatherThanBeingInventedOrDiscarded() throws Exception {
        source.update("UPDATE detection_creation_job SET status='CANCELLED',owner_token=NULL");fixture.copy();
        var value=target.queryForMap("SELECT claim_token,lease_expires_at,status FROM workflow_instance WHERE kind='DETECTION_CREATION'");
        assertThat(value.get("claim_token")).isNull();assertThat(value.get("lease_expires_at")).isNotNull();assertThat(value.get("status")).isEqualTo("CANCELLED");
    }
    private void assertTargetEmpty(){
        assertThat(target.queryForObject("SELECT COUNT(*) FROM workflow_instance WHERE kind LIKE 'DETECTION_%'",Integer.class)).isZero();
        assertThat(target.queryForObject("SELECT COUNT(*) FROM runtime_state WHERE namespace='DETECTION_CREATION_OWNER'",Integer.class)).isZero();
    }
    private void seed() throws Exception {
        source.update("INSERT INTO detection_creation_owner(user_id) VALUES(99)");
        source.update("INSERT INTO detection_creation_job(id,command_id,actor_user_id,actor_username,actor_role,request_id,proposal_id,task_id,dispatch_id,session_id,preview_json,preview_sha256,status,owner_token,lease_until,reason_code,created_at,updated_at,revision,bucket_name,source_prefix,manifest_sha256) VALUES(91,?,99,'null','SUPERVISOR','creation-request','proposal-1','task-created','dispatch-created','session-1',?,?,'NEEDS_REVIEW','creation-owner',?,'TRANSFER_INTERRUPTED',?,?,8,'bucket','source/',?)",
                COMMAND,PREVIEW,DetectionExecutionPersistence.sha(PREVIEW),WALL,WALL,WALL,"a".repeat(64));
        source.update("INSERT INTO detection_creation_object(id,command_id,image_index,file_id,object_key,content_sha256,byte_length,content_type,state,upload_token,etag,object_version,oss_request_id,updated_at) VALUES(9007199254740993,?,0,?,'source/原图.jpg',?,3,'image/jpeg','STORED','upload-owner','etag',NULL,'oss-request',?)",COMMAND,FILE,"b".repeat(64),WALL);
        source.update("INSERT INTO detection_creation_object(command_id,image_index,file_id,object_key,content_sha256,byte_length,content_type,state,upload_token,updated_at) VALUES(?,0,?,'orphan/原图.jpg',?,3,'image/jpeg','UPLOADING','orphan-upload-owner',?)",ORPHAN,FILE,"c".repeat(64),WALL);
        source.update("INSERT INTO detection_creation_review(id,check_id,command_id,actor_user_id,request_id,expected_revision,action,status,worker_token,lease_until,checked_count,verified_count,evidence_json,evidence_sha256,completed_revision,created_at,updated_at) VALUES(97,?,?,99,'review-request',7,'CHECK','VERIFIED','check-owner',?,1,1,?,?,8,?,?)",CHECK,COMMAND,WALL,EVIDENCE,DetectionExecutionPersistence.sha(EVIDENCE),WALL,WALL);
        String result=new ObjectMapper().writeValueAsString(Map.of("commandId","receipt-1","operation","CREATE","taskId","task-created","dispatchId","dispatch-created","status","QUEUED"));
        source.update("INSERT INTO detection_execution_command(command_id,actor_user_id,request_id,command_type,payload_sha256,proposal_id,task_id,dispatch_id,result_json,created_at) VALUES('receipt-1',99,'command-request','CREATE',?,NULL,'task-created','dispatch-created',?,?)","d".repeat(64),result,WALL);
        String event=" { \"eventId\": \"dispatch-event\", \"taskId\": \"task-created\", \"dispatchId\": \"dispatch-created\", \"label\": \"原文\", \"threshold\": 0.5000 } ";
        source.update("INSERT INTO detection_dispatch_outbox(id,event_id,task_id,dispatch_id,payload_json,payload_sha256,actor_user_id,request_id,status,attempts,lease_token,lease_until,next_attempt_at,last_error_code,created_at,updated_at) VALUES(101,'dispatch-event','task-created','dispatch-created',?,?,99,'dispatch-request','SENDING',3,'delivery-owner',?,?,'ACK_UNCONFIRMED',?,?)",event,"e".repeat(64),WALL,WALL,WALL,WALL);
        source.update("INSERT INTO detection_worker_receipt(task_id,dispatch_id,event_id,payload_sha256,owner_id,status,started_at,updated_at) VALUES('task-running','dispatch-1','worker-running-event',?,'worker-running-owner','RUNNING',?,?)","f".repeat(64),WALL,WALL);
        String finished=" { \"taskId\": \"task-completed\", \"dispatchId\": \"dispatch-2\", \"eventId\": \"task-completed-dispatch-2-finished\", \"eventType\": \"DETECTION_TASK_FINISHED\", \"status\": \"COMPLETED\" } ";
        source.update("INSERT INTO detection_worker_receipt(task_id,dispatch_id,event_id,payload_sha256,owner_id,status,result_json,result_sha256,started_at,updated_at) VALUES('task-completed','dispatch-2','worker-completed-event',?,'worker-completed-owner','COMPLETED',?,?,?,?)","f".repeat(64),finished,DetectionExecutionPersistence.sha(finished),WALL,WALL);
    }
}
