package com.ruanzhu.doorhandle.module.detection.service;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.framework.persistence.JdbcTransactions;
import java.math.BigInteger;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.LocalDateTime;
import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;

/** Closed detection-owned identity records. SQL addresses compact physical relations directly. */
public final class DetectionIdentityPersistence {
    public record ControlV1(Integer controlId, Long activationRevision, String legacySource) { }
    public record BindingHeadV1(String taskId, String identityRole, String eventSha256, String legacyId, String legacyEventId, String legacySource) { }
    public record CommandV1(Long actorUserId, String legacyCreatedAt) { }
    public record MapBatchV1(Long actorUserId, String actorName, long revisionBefore, long revisionAfter,
                             int appliedCount, String legacyId, String legacyCreatedAt) { }
    public record MapItemV1(String batchId, String taskId, String identityRole, String sourceName,
                            String sourceSnapshot, Long previousUserId, String previousIdentityName,
                            long targetUserId, String targetUsername, String targetRole, String targetRevision,
                            String confirmationBasis, String legacyId) { }
    public record ReportV1(Long actorUserId, String actorName, String protocol, long controlRevision,
                           String identityMode, String sourceMode, String startedAt, String finishedAt,
                           long taskCount, long roleCount, long issueCount, String datasetSha256,
                           String previousReportId, String summaryJson, String legacyId) { }
    public record AssignmentV1(String taskId, Long actorUserId, String actorName, long assigneeUserId,
                               String assigneeName, String assigneeRevision, String requestId,
                               String legacyId, String legacyCreatedAt) { }
    public record BindingEventV1(String taskId, String identityRole, Long boundUserId, String boundIdentityName,
                                 String targetRevision, Long actorUserId, String actorName, String sourceKind,
                                 String requestId, String sourceBatchId, String legacyId, String legacyCreatedAt) { }
    public record ReconciliationItemV1(String reportId, String taskId, String identityRole, String existingName,
                                       Long existingUserId, String identityName, String currentUsername,
                                       String currentRole, String currentRevision, String sourceKind,
                                       String sourceRequestId, String sourceSha256, String reasonCodes,
                                       String itemSha256, String legacyId) { }
    public record MissingNameV1(String batchId, String taskId, String identityRole, String originalName,
                                String sourceSnapshot, long targetUserId, String evidenceReference,
                                String legacyCreatedAt) { }

        public static final String CONTROL = """
        SELECT CASE WHEN JSON_TYPE(JSON_EXTRACT(p.payload_json,'$.controlId'))='INTEGER' THEN CAST(JSON_UNQUOTE(JSON_EXTRACT(p.payload_json,'$.controlId')) AS SIGNED) END AS control_id,
           p.state_code AS mode,
           p.revision AS revision
        FROM runtime_state p
        WHERE p.namespace='DETECTION_IDENTITY_CONTROL' AND owner_id=0 AND p.payload_version=1
        """;

    public static final String SOURCE_CONTROL = """
        SELECT CASE WHEN JSON_TYPE(JSON_EXTRACT(p.payload_json,'$.controlId'))='INTEGER' THEN CAST(JSON_UNQUOTE(JSON_EXTRACT(p.payload_json,'$.controlId')) AS SIGNED) END AS control_id,
           p.state_code AS mode,
           CASE WHEN JSON_TYPE(JSON_EXTRACT(p.payload_json,'$.activationRevision'))='INTEGER' THEN CAST(JSON_UNQUOTE(JSON_EXTRACT(p.payload_json,'$.activationRevision')) AS SIGNED) END AS activation_revision
        FROM runtime_state p
        WHERE p.namespace='DETECTION_IDENTITY_SOURCE_CONTROL' AND owner_id=0 AND p.payload_version=1
        """;

    public static final String COMMANDS = """
        SELECT p.request_id AS request_id,
           CASE WHEN JSON_TYPE(JSON_EXTRACT(p.payload_json,'$.actorUserId'))='INTEGER' THEN CAST(JSON_UNQUOTE(JSON_EXTRACT(p.payload_json,'$.actorUserId')) AS SIGNED) END AS actor_user_id,
           p.request_sha256 AS request_sha256,
           p.result_json AS result_json,
           CASE WHEN JSON_TYPE(JSON_EXTRACT(p.payload_json,'$.legacyCreatedAt'))='STRING' THEN CAST(JSON_UNQUOTE(JSON_EXTRACT(p.payload_json,'$.legacyCreatedAt')) AS DATETIME(6)) ELSE DATE_ADD(p.created_at,INTERVAL 8 HOUR) END AS created_at
        FROM workflow_instance p
        WHERE p.kind='DETECTION_IDENTITY_COMMAND' AND p.payload_version=1
        """;

    public static final String BATCHES = """
        SELECT COALESCE(p.identity_source_id,p.id) AS id,
           p.request_id AS request_id,
           CASE WHEN JSON_TYPE(JSON_EXTRACT(p.payload_json,'$.actorUserId'))='INTEGER' THEN CAST(JSON_UNQUOTE(JSON_EXTRACT(p.payload_json,'$.actorUserId')) AS SIGNED) END AS actor_user_id,
           CASE WHEN JSON_TYPE(JSON_EXTRACT(p.payload_json,'$.actorName'))='STRING' THEN JSON_UNQUOTE(JSON_EXTRACT(p.payload_json,'$.actorName')) END AS actor_name,
           p.request_sha256 AS command_sha256,
           CASE WHEN JSON_TYPE(JSON_EXTRACT(p.payload_json,'$.revisionBefore'))='INTEGER' THEN CAST(JSON_UNQUOTE(JSON_EXTRACT(p.payload_json,'$.revisionBefore')) AS SIGNED) END AS revision_before,
           CASE WHEN JSON_TYPE(JSON_EXTRACT(p.payload_json,'$.revisionAfter'))='INTEGER' THEN CAST(JSON_UNQUOTE(JSON_EXTRACT(p.payload_json,'$.revisionAfter')) AS SIGNED) END AS revision_after,
           CASE WHEN JSON_TYPE(JSON_EXTRACT(p.payload_json,'$.appliedCount'))='INTEGER' THEN CAST(JSON_UNQUOTE(JSON_EXTRACT(p.payload_json,'$.appliedCount')) AS SIGNED) END AS applied_count,
           p.result_json AS result_json,
           CASE WHEN JSON_TYPE(JSON_EXTRACT(p.payload_json,'$.legacyCreatedAt'))='STRING' THEN CAST(JSON_UNQUOTE(JSON_EXTRACT(p.payload_json,'$.legacyCreatedAt')) AS DATETIME(6)) ELSE DATE_ADD(p.created_at,INTERVAL 8 HOUR) END AS created_at
        FROM workflow_instance p
        WHERE p.kind='DETECTION_IDENTITY_MAP_BATCH' AND p.payload_version=1
        """;

    public static final String MAPPINGS = """
        SELECT COALESCE(p.identity_source_id,p.id) AS id,
           p.identity_parent_id AS batch_id,
           p.identity_task_id AS task_id,
           p.identity_role AS identity_role,
           CASE WHEN JSON_TYPE(JSON_EXTRACT(p.payload_json,'$.sourceName'))='STRING' THEN JSON_UNQUOTE(JSON_EXTRACT(p.payload_json,'$.sourceName')) END AS source_name,
           CASE WHEN JSON_TYPE(JSON_EXTRACT(p.payload_json,'$.sourceSnapshot'))='STRING' THEN JSON_UNQUOTE(JSON_EXTRACT(p.payload_json,'$.sourceSnapshot')) END AS source_snapshot,
           CASE WHEN JSON_TYPE(JSON_EXTRACT(p.payload_json,'$.previousUserId'))='INTEGER' THEN CAST(JSON_UNQUOTE(JSON_EXTRACT(p.payload_json,'$.previousUserId')) AS SIGNED) END AS previous_user_id,
           CASE WHEN JSON_TYPE(JSON_EXTRACT(p.payload_json,'$.previousIdentityName'))='STRING' THEN JSON_UNQUOTE(JSON_EXTRACT(p.payload_json,'$.previousIdentityName')) END AS previous_identity_name,
           CASE WHEN JSON_TYPE(JSON_EXTRACT(p.payload_json,'$.targetUserId'))='INTEGER' THEN CAST(JSON_UNQUOTE(JSON_EXTRACT(p.payload_json,'$.targetUserId')) AS SIGNED) END AS target_user_id,
           CASE WHEN JSON_TYPE(JSON_EXTRACT(p.payload_json,'$.targetUsername'))='STRING' THEN JSON_UNQUOTE(JSON_EXTRACT(p.payload_json,'$.targetUsername')) END AS target_username,
           CASE WHEN JSON_TYPE(JSON_EXTRACT(p.payload_json,'$.targetRole'))='STRING' THEN JSON_UNQUOTE(JSON_EXTRACT(p.payload_json,'$.targetRole')) END AS target_role,
           CASE WHEN JSON_TYPE(JSON_EXTRACT(p.payload_json,'$.targetRevision'))='STRING' THEN JSON_UNQUOTE(JSON_EXTRACT(p.payload_json,'$.targetRevision')) END AS target_revision,
           CASE WHEN JSON_TYPE(JSON_EXTRACT(p.payload_json,'$.confirmationBasis'))='STRING' THEN JSON_UNQUOTE(JSON_EXTRACT(p.payload_json,'$.confirmationBasis')) END AS confirmation_basis
        FROM workflow_instance p
        WHERE p.kind='DETECTION_IDENTITY_MAP_ITEM' AND p.payload_version=1
        """;

    public static final String EVENTS = """
        SELECT COALESCE(p.identity_source_id,p.id) AS id,
           p.identity_task_id AS task_id,
           p.identity_role AS identity_role,
           p.revision AS revision,
           p.previous_sha256 AS previous_sha256,
           p.event_sha256 AS event_sha256,
           p.identity_parent_id AS source_batch_id,
           CASE WHEN JSON_TYPE(JSON_EXTRACT(p.payload_json,'$.legacyCreatedAt'))='STRING' THEN CAST(JSON_UNQUOTE(JSON_EXTRACT(p.payload_json,'$.legacyCreatedAt')) AS DATETIME(6)) ELSE DATE_ADD(p.occurred_at,INTERVAL 8 HOUR) END AS created_at,
           CASE WHEN JSON_TYPE(JSON_EXTRACT(p.payload_json,'$.boundUserId'))='INTEGER' THEN CAST(JSON_UNQUOTE(JSON_EXTRACT(p.payload_json,'$.boundUserId')) AS SIGNED) END AS bound_user_id,
           CASE WHEN JSON_TYPE(JSON_EXTRACT(p.payload_json,'$.boundIdentityName'))='STRING' THEN JSON_UNQUOTE(JSON_EXTRACT(p.payload_json,'$.boundIdentityName')) END AS bound_identity_name,
           CASE WHEN JSON_TYPE(JSON_EXTRACT(p.payload_json,'$.targetRevision'))='STRING' THEN JSON_UNQUOTE(JSON_EXTRACT(p.payload_json,'$.targetRevision')) END AS target_revision,
           CASE WHEN JSON_TYPE(JSON_EXTRACT(p.payload_json,'$.actorUserId'))='INTEGER' THEN CAST(JSON_UNQUOTE(JSON_EXTRACT(p.payload_json,'$.actorUserId')) AS SIGNED) END AS actor_user_id,
           CASE WHEN JSON_TYPE(JSON_EXTRACT(p.payload_json,'$.actorName'))='STRING' THEN JSON_UNQUOTE(JSON_EXTRACT(p.payload_json,'$.actorName')) END AS actor_name,
           CASE WHEN JSON_TYPE(JSON_EXTRACT(p.payload_json,'$.sourceKind'))='STRING' THEN JSON_UNQUOTE(JSON_EXTRACT(p.payload_json,'$.sourceKind')) END AS source_kind,
           CASE WHEN JSON_TYPE(JSON_EXTRACT(p.payload_json,'$.requestId'))='STRING' THEN JSON_UNQUOTE(JSON_EXTRACT(p.payload_json,'$.requestId')) END AS request_id
        FROM audit_event p
        WHERE p.kind='DETECTION_IDENTITY_BINDING_EVENT' AND p.payload_version=1
        """;

    public static final String HEADS = """
        SELECT CASE WHEN JSON_TYPE(JSON_EXTRACT(p.payload_json,'$.legacyId'))='STRING' THEN CAST(JSON_UNQUOTE(JSON_EXTRACT(p.payload_json,'$.legacyId')) AS UNSIGNED) END AS id,
           p.identity_task_id AS task_id,
           p.identity_role AS identity_role,
           COALESCE(a.identity_source_id,a.id) AS event_id,
           p.revision AS revision,
           CASE WHEN JSON_TYPE(JSON_EXTRACT(p.payload_json,'$.eventSha256'))='STRING' THEN JSON_UNQUOTE(JSON_EXTRACT(p.payload_json,'$.eventSha256')) END AS event_sha256
        FROM runtime_state p LEFT JOIN audit_event a ON a.kind='DETECTION_IDENTITY_BINDING_EVENT' AND a.event_id=p.current_ref
        WHERE p.namespace='DETECTION_IDENTITY_BINDING' AND owner_id=0 AND p.payload_version=1
        """;

    public static final String MISSING = """
        SELECT p.identity_parent_id AS batch_id,
           p.identity_task_id AS task_id,
           p.identity_role AS identity_role,
           CASE WHEN JSON_TYPE(JSON_EXTRACT(p.payload_json,'$.originalName'))='STRING' THEN JSON_UNQUOTE(JSON_EXTRACT(p.payload_json,'$.originalName')) END AS original_name,
           CASE WHEN JSON_TYPE(JSON_EXTRACT(p.payload_json,'$.sourceSnapshot'))='STRING' THEN JSON_UNQUOTE(JSON_EXTRACT(p.payload_json,'$.sourceSnapshot')) END AS source_snapshot,
           CASE WHEN JSON_TYPE(JSON_EXTRACT(p.payload_json,'$.targetUserId'))='INTEGER' THEN CAST(JSON_UNQUOTE(JSON_EXTRACT(p.payload_json,'$.targetUserId')) AS SIGNED) END AS target_user_id,
           CASE WHEN JSON_TYPE(JSON_EXTRACT(p.payload_json,'$.evidenceReference'))='STRING' THEN JSON_UNQUOTE(JSON_EXTRACT(p.payload_json,'$.evidenceReference')) END AS evidence_reference,
           CASE WHEN JSON_TYPE(JSON_EXTRACT(p.payload_json,'$.legacyCreatedAt'))='STRING' THEN CAST(JSON_UNQUOTE(JSON_EXTRACT(p.payload_json,'$.legacyCreatedAt')) AS DATETIME(6)) ELSE DATE_ADD(p.occurred_at,INTERVAL 8 HOUR) END AS created_at
        FROM audit_event p
        WHERE p.kind='DETECTION_IDENTITY_MISSING_NAME' AND p.payload_version=1
        """;

    public static final String REPORTS = """
        SELECT COALESCE(p.identity_source_id,p.id) AS id,
           p.request_id AS request_id,
           p.request_sha256 AS request_sha256,
           CASE WHEN JSON_TYPE(JSON_EXTRACT(p.payload_json,'$.actorUserId'))='INTEGER' THEN CAST(JSON_UNQUOTE(JSON_EXTRACT(p.payload_json,'$.actorUserId')) AS SIGNED) END AS actor_user_id,
           CASE WHEN JSON_TYPE(JSON_EXTRACT(p.payload_json,'$.actorName'))='STRING' THEN JSON_UNQUOTE(JSON_EXTRACT(p.payload_json,'$.actorName')) END AS actor_name,
           CASE WHEN JSON_TYPE(JSON_EXTRACT(p.payload_json,'$.protocol'))='STRING' THEN JSON_UNQUOTE(JSON_EXTRACT(p.payload_json,'$.protocol')) END AS protocol,
           CASE WHEN JSON_TYPE(JSON_EXTRACT(p.payload_json,'$.controlRevision'))='INTEGER' THEN CAST(JSON_UNQUOTE(JSON_EXTRACT(p.payload_json,'$.controlRevision')) AS SIGNED) END AS control_revision,
           CASE WHEN JSON_TYPE(JSON_EXTRACT(p.payload_json,'$.identityMode'))='STRING' THEN JSON_UNQUOTE(JSON_EXTRACT(p.payload_json,'$.identityMode')) END AS identity_mode,
           CASE WHEN JSON_TYPE(JSON_EXTRACT(p.payload_json,'$.sourceMode'))='STRING' THEN JSON_UNQUOTE(JSON_EXTRACT(p.payload_json,'$.sourceMode')) END AS source_mode,
           CAST(CASE WHEN JSON_TYPE(JSON_EXTRACT(p.payload_json,'$.startedAt'))='STRING' THEN JSON_UNQUOTE(JSON_EXTRACT(p.payload_json,'$.startedAt')) END AS DATETIME(6)) AS started_at,
           CAST(CASE WHEN JSON_TYPE(JSON_EXTRACT(p.payload_json,'$.finishedAt'))='STRING' THEN JSON_UNQUOTE(JSON_EXTRACT(p.payload_json,'$.finishedAt')) END AS DATETIME(6)) AS finished_at,
           CASE WHEN JSON_TYPE(JSON_EXTRACT(p.payload_json,'$.taskCount'))='INTEGER' THEN CAST(JSON_UNQUOTE(JSON_EXTRACT(p.payload_json,'$.taskCount')) AS SIGNED) END AS task_count,
           CASE WHEN JSON_TYPE(JSON_EXTRACT(p.payload_json,'$.roleCount'))='INTEGER' THEN CAST(JSON_UNQUOTE(JSON_EXTRACT(p.payload_json,'$.roleCount')) AS SIGNED) END AS role_count,
           CASE WHEN JSON_TYPE(JSON_EXTRACT(p.payload_json,'$.issueCount'))='INTEGER' THEN CAST(JSON_UNQUOTE(JSON_EXTRACT(p.payload_json,'$.issueCount')) AS SIGNED) END AS issue_count,
           CASE WHEN JSON_TYPE(JSON_EXTRACT(p.payload_json,'$.datasetSha256'))='STRING' THEN JSON_UNQUOTE(JSON_EXTRACT(p.payload_json,'$.datasetSha256')) END AS dataset_sha256,
           CASE WHEN JSON_TYPE(JSON_EXTRACT(p.payload_json,'$.previousReportId'))='STRING' THEN CAST(JSON_UNQUOTE(JSON_EXTRACT(p.payload_json,'$.previousReportId')) AS UNSIGNED) END AS previous_report_id,
           CASE WHEN JSON_TYPE(JSON_EXTRACT(p.payload_json,'$.summaryJson'))='STRING' THEN JSON_UNQUOTE(JSON_EXTRACT(p.payload_json,'$.summaryJson')) END AS summary_json
        FROM workflow_instance p
        WHERE p.kind='DETECTION_IDENTITY_REPORT' AND p.payload_version=1
        """;

    public static final String ISSUES = """
        SELECT COALESCE(p.identity_source_id,p.id) AS id,
           p.identity_parent_id AS report_id,
           p.identity_task_id AS task_id,
           p.identity_role AS identity_role,
           CASE WHEN JSON_TYPE(JSON_EXTRACT(p.payload_json,'$.existingName'))='STRING' THEN JSON_UNQUOTE(JSON_EXTRACT(p.payload_json,'$.existingName')) END AS existing_name,
           CASE WHEN JSON_TYPE(JSON_EXTRACT(p.payload_json,'$.existingUserId'))='INTEGER' THEN CAST(JSON_UNQUOTE(JSON_EXTRACT(p.payload_json,'$.existingUserId')) AS SIGNED) END AS existing_user_id,
           CASE WHEN JSON_TYPE(JSON_EXTRACT(p.payload_json,'$.identityName'))='STRING' THEN JSON_UNQUOTE(JSON_EXTRACT(p.payload_json,'$.identityName')) END AS identity_name,
           CASE WHEN JSON_TYPE(JSON_EXTRACT(p.payload_json,'$.currentUsername'))='STRING' THEN JSON_UNQUOTE(JSON_EXTRACT(p.payload_json,'$.currentUsername')) END AS current_username,
           CASE WHEN JSON_TYPE(JSON_EXTRACT(p.payload_json,'$.currentRole'))='STRING' THEN JSON_UNQUOTE(JSON_EXTRACT(p.payload_json,'$.currentRole')) END AS current_role,
           CASE WHEN JSON_TYPE(JSON_EXTRACT(p.payload_json,'$.currentRevision'))='STRING' THEN JSON_UNQUOTE(JSON_EXTRACT(p.payload_json,'$.currentRevision')) END AS current_revision,
           CASE WHEN JSON_TYPE(JSON_EXTRACT(p.payload_json,'$.sourceKind'))='STRING' THEN JSON_UNQUOTE(JSON_EXTRACT(p.payload_json,'$.sourceKind')) END AS source_kind,
           CASE WHEN JSON_TYPE(JSON_EXTRACT(p.payload_json,'$.sourceRequestId'))='STRING' THEN JSON_UNQUOTE(JSON_EXTRACT(p.payload_json,'$.sourceRequestId')) END AS source_request_id,
           CASE WHEN JSON_TYPE(JSON_EXTRACT(p.payload_json,'$.sourceSha256'))='STRING' THEN JSON_UNQUOTE(JSON_EXTRACT(p.payload_json,'$.sourceSha256')) END AS source_sha256,
           CASE WHEN JSON_TYPE(JSON_EXTRACT(p.payload_json,'$.reasonCodes'))='STRING' THEN JSON_UNQUOTE(JSON_EXTRACT(p.payload_json,'$.reasonCodes')) END AS reason_codes,
           CASE WHEN JSON_TYPE(JSON_EXTRACT(p.payload_json,'$.itemSha256'))='STRING' THEN JSON_UNQUOTE(JSON_EXTRACT(p.payload_json,'$.itemSha256')) END AS item_sha256
        FROM audit_event p
        WHERE p.kind='DETECTION_IDENTITY_RECON_ITEM' AND p.payload_version=1
        """;

    public static final String ASSIGNMENTS = """
        SELECT COALESCE(p.identity_source_id,p.id) AS id,
           p.identity_task_id AS task_id,
           p.revision AS revision,
           CASE WHEN JSON_TYPE(JSON_EXTRACT(p.payload_json,'$.legacyCreatedAt'))='STRING' THEN CAST(JSON_UNQUOTE(JSON_EXTRACT(p.payload_json,'$.legacyCreatedAt')) AS DATETIME(6)) ELSE DATE_ADD(p.occurred_at,INTERVAL 8 HOUR) END AS created_at,
           CASE WHEN JSON_TYPE(JSON_EXTRACT(p.payload_json,'$.actorUserId'))='INTEGER' THEN CAST(JSON_UNQUOTE(JSON_EXTRACT(p.payload_json,'$.actorUserId')) AS SIGNED) END AS actor_user_id,
           CASE WHEN JSON_TYPE(JSON_EXTRACT(p.payload_json,'$.actorName'))='STRING' THEN JSON_UNQUOTE(JSON_EXTRACT(p.payload_json,'$.actorName')) END AS actor_name,
           CASE WHEN JSON_TYPE(JSON_EXTRACT(p.payload_json,'$.assigneeUserId'))='INTEGER' THEN CAST(JSON_UNQUOTE(JSON_EXTRACT(p.payload_json,'$.assigneeUserId')) AS SIGNED) END AS assignee_user_id,
           CASE WHEN JSON_TYPE(JSON_EXTRACT(p.payload_json,'$.assigneeName'))='STRING' THEN JSON_UNQUOTE(JSON_EXTRACT(p.payload_json,'$.assigneeName')) END AS assignee_name,
           CASE WHEN JSON_TYPE(JSON_EXTRACT(p.payload_json,'$.assigneeRevision'))='STRING' THEN JSON_UNQUOTE(JSON_EXTRACT(p.payload_json,'$.assigneeRevision')) END AS assignee_revision,
           CASE WHEN JSON_TYPE(JSON_EXTRACT(p.payload_json,'$.requestId'))='STRING' THEN JSON_UNQUOTE(JSON_EXTRACT(p.payload_json,'$.requestId')) END AS request_id
        FROM audit_event p
        WHERE p.kind='DETECTION_ASSIGNMENT_IDENTITY' AND p.payload_version=1
        """;

    private final JdbcTemplate jdbc;
    private final ObjectMapper json;
    public DetectionIdentityPersistence(JdbcTemplate jdbc, ObjectMapper json) {
        this.jdbc=Objects.requireNonNull(jdbc);
        this.json=json.copy().setSerializationInclusion(JsonInclude.Include.ALWAYS)
                .enable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES);
    }
    public void validateSchema() {
        jdbc.queryForList("SELECT identity_task_id,identity_role,current_ref,payload_version,payload_json FROM runtime_state WHERE 1=0");
        jdbc.queryForList("SELECT identity_source_id,identity_parent_id,identity_task_id,identity_role,identity_protocol FROM workflow_instance WHERE 1=0");
        jdbc.queryForList("SELECT identity_source_id,identity_parent_id,identity_task_id,identity_role FROM audit_event WHERE 1=0");
    }
    /** Explicit row locks, independent of the optimizer's derived-table merge decisions. */
    public Map<String,Object> control(boolean source, boolean lock) {
        var rows=jdbc.queryForList("SELECT * FROM runtime_state WHERE namespace=? AND owner_id=0 AND scope_key='1'"+(lock?" FOR UPDATE":""),
                source?"DETECTION_IDENTITY_SOURCE_CONTROL":"DETECTION_IDENTITY_CONTROL");
        if(rows.size()!=1)throw new IllegalStateException("Identity control is absent or ambiguous; initialize the compact schema explicitly");
        var row=rows.get(0);version(row);var payload=read((String)row.get("payload_json"),ControlV1.class);
        if(!Integer.valueOf(1).equals(payload.controlId()))throw new IllegalStateException("Identity control payload differs");
        var result=new LinkedHashMap<String,Object>();result.put("mode",row.get("state_code"));result.put("revision",row.get("revision"));
        result.put("activation_revision",payload.activationRevision());return result;
    }
    public int activateControl() {
        JdbcTransactions.requireActive(jdbc);
        return jdbc.update("UPDATE runtime_state SET state_code='ACTIVE',revision=revision+1,updated_at=UTC_TIMESTAMP(6) "
                +"WHERE namespace='DETECTION_IDENTITY_CONTROL' AND owner_id=0 AND scope_key='1'");
    }
    public int revision(long next,long expected) {
        JdbcTransactions.requireActive(jdbc);
        return jdbc.update("UPDATE runtime_state SET revision=?,updated_at=UTC_TIMESTAMP(6) "
                +"WHERE namespace='DETECTION_IDENTITY_CONTROL' AND owner_id=0 AND scope_key='1' AND revision=?",next,expected);
    }
    public int activateSource(long revision) {
        JdbcTransactions.requireActive(jdbc);
        return jdbc.update("UPDATE runtime_state SET state_code='ACTIVE',payload_json=JSON_SET(payload_json,'$.activationRevision',?),updated_at=UTC_TIMESTAMP(6) "
                +"WHERE namespace='DETECTION_IDENTITY_SOURCE_CONTROL' AND owner_id=0 AND scope_key='1' AND state_code='COLLECTING'",revision);
    }
    public void command(String request,long actor,String digest,String result) {
        JdbcTransactions.requireActive(jdbc);
        workflow("DETECTION_IDENTITY_COMMAND",request,digest,actor,"COMPLETED",new CommandV1(actor,null),result,null);
    }
    public void mappingBatch(String request,long actor,String actorName,String digest,long before,long after,int count,String result) {
        JdbcTransactions.requireActive(jdbc);
        workflow("DETECTION_IDENTITY_MAP_BATCH",request,digest,actor,"COMPLETED",new MapBatchV1(actor,actorName,before,after,count,null,null),result,after);
    }
    public void mappingItem(long actor,long batch,String task,String role,String source,String snapshot,Object priorId,
                            Object priorName,long target,String targetName,String targetRole,String targetRevision,String basis) {
        JdbcTransactions.requireActive(jdbc);
        var payload=new MapItemV1(decimal(batch),task,role,source,snapshot,number(priorId),(String)priorName,target,targetName,targetRole,targetRevision,basis,null);
        workflow("DETECTION_IDENTITY_MAP_ITEM",UUID.randomUUID().toString(),sha(write(payload)),actor,"COMPLETED",payload,null,null);
    }
    public void missingName(long actor,long batch,String task,String role,Object original,String snapshot,long target,String reference) {
        JdbcTransactions.requireActive(jdbc);
        var payload=new MissingNameV1(decimal(batch),task,role,(String)original,snapshot,target,reference,null);
        audit("DETECTION_IDENTITY_MISSING_NAME",actor,actor,task,"CONFIRMED",null,null,null,"IDMAP:"+batch,
                identityScope(task,role),null,null,write(payload));
    }
    public void assignment(String task,long revision,long actor,String actorName,long target,String targetName,String targetRevision,String request) {
        JdbcTransactions.requireActive(jdbc);
        var payload=new AssignmentV1(task,actor,actorName,target,targetName,targetRevision,request,null,null);
        audit("DETECTION_ASSIGNMENT_IDENTITY",target,actor,task,"ASSIGNED",revision,identityScope(task,"assignment"),revision,
                null,request,null,null,write(payload));
    }
    public long bindingEvent(String task,String role,long revision,Long subject,String name,String targetRevision,
                             Long actor,String actorName,String kind,String request,Long batch,String previous,String digest) {
        JdbcTransactions.requireActive(jdbc);
        var payload=new BindingEventV1(task,role,subject,name,targetRevision,actor,actorName,kind,request,
                batch==null?null:decimal(batch),null,null);
        return audit("DETECTION_IDENTITY_BINDING_EVENT",positive(subject),positive(actor),task,kind,revision,
                identityScope(task,role),revision,identityScope(task,role),request,previous,digest,write(payload));
    }
    public List<Map<String,Object>> head(String task,String role,boolean lock) {
        return jdbc.queryForList("SELECT a.identity_source_id,a.id AS shared_event_id,COALESCE(a.identity_source_id,a.id) AS event_id,"
                +"r.revision,JSON_UNQUOTE(JSON_EXTRACT(r.payload_json,'$.eventSha256')) AS event_sha256 FROM runtime_state r LEFT JOIN audit_event a "
                +"ON a.kind='DETECTION_IDENTITY_BINDING_EVENT' AND a.event_id=r.current_ref "
                +"WHERE r.namespace='DETECTION_IDENTITY_BINDING' AND r.owner_id=0 AND r.scope_key=?"+(lock?" FOR UPDATE":""),identityScope(task,role));
    }
    public int head(String task,String role,long event,long revision,String digest,Long expected) {
        JdbcTransactions.requireActive(jdbc);
        var ids=jdbc.queryForList("SELECT event_id FROM audit_event WHERE kind='DETECTION_IDENTITY_BINDING_EVENT' "
                +"AND COALESCE(identity_source_id,id)=? AND identity_task_id=? AND identity_role=? AND revision=? AND event_sha256=?",
                event,task,role,revision,digest);
        if(ids.size()!=1)throw new IllegalStateException("Identity head requires its exact immutable event");
        String reference=(String)ids.get(0).get("event_id"),scope=identityScope(task,role);
        if(expected==null) {
            var payload=new BindingHeadV1(task,role,digest,null,null,null);
            return jdbc.update("INSERT INTO runtime_state(namespace,owner_id,scope_key,revision,current_ref,payload_version,payload_json,created_at,updated_at) "
                    +"VALUES('DETECTION_IDENTITY_BINDING',0,?,?,?,1,?,UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))",scope,revision,reference,write(payload));
        }
        return jdbc.update("UPDATE runtime_state SET current_ref=?,revision=?,payload_json=JSON_SET(payload_json,'$.eventSha256',?),updated_at=UTC_TIMESTAMP(6) "
                +"WHERE namespace='DETECTION_IDENTITY_BINDING' AND owner_id=0 AND scope_key=? AND revision=?",reference,revision,digest,scope,expected);
    }
    public void report(String request,long actor,String actorName,String digest,String protocol,long revision,String mode,String sourceMode,
                       LocalDateTime started,LocalDateTime finished,String dataset,Long previous,String summary) {
        JdbcTransactions.requireActive(jdbc);
        var payload=new ReportV1(actor,actorName,protocol,revision,mode,sourceMode,started.toString(),finished.toString(),0,0,0,dataset,
                previous==null?null:decimal(previous),summary,null);
        workflow("DETECTION_IDENTITY_REPORT",request,digest,actor,"STARTED",payload,null,revision);
    }
    public int finishReport(LocalDateTime finished,long tasks,long roles,long issues,String dataset,String summary,long report) {
        JdbcTransactions.requireActive(jdbc);
        var rows=jdbc.queryForList("SELECT id,payload_version,payload_json FROM workflow_instance WHERE kind='DETECTION_IDENTITY_REPORT' AND COALESCE(identity_source_id,id)=? FOR UPDATE",report);
        if(rows.size()!=1)return 0;
        var row=rows.get(0);version(row);var old=read((String)row.get("payload_json"),ReportV1.class);
        var payload=new ReportV1(old.actorUserId(),old.actorName(),old.protocol(),old.controlRevision(),old.identityMode(),old.sourceMode(),
                old.startedAt(),finished.toString(),tasks,roles,issues,dataset,old.previousReportId(),summary,old.legacyId());
        return jdbc.update("UPDATE workflow_instance SET payload_json=?,status='COMPLETED',updated_at=UTC_TIMESTAMP(6),finished_at=UTC_TIMESTAMP(6) "
                +"WHERE kind='DETECTION_IDENTITY_REPORT' AND id=? AND status='STARTED'",write(payload),row.get("id"));
    }
    public int[] reconciliationItems(long actor,List<Object[]> rows) {
        JdbcTransactions.requireActive(jdbc);
        int[] counts=new int[rows.size()];int i=0;
        for(var row:rows) {
            var payload=new ReconciliationItemV1(decimal(((Number)row[0]).longValue()),(String)row[1],(String)row[2],(String)row[3],number(row[4]),
                    (String)row[5],(String)row[6],(String)row[7],(String)row[8],(String)row[9],(String)row[10],(String)row[11],(String)row[12],(String)row[13],null);
            audit("DETECTION_IDENTITY_RECON_ITEM",actor,actor,(String)row[1],"OBSERVED",null,null,null,
                    "IDREPORT:"+row[0],identityScope((String)row[1],(String)row[2]),null,null,write(payload));counts[i++]=1;
        }
        return counts;
    }
    private void workflow(String kind,String request,String fingerprint,long actor,String status,Object payload,String result,Long revision) {
        if(actor<1||request==null||request.isBlank()||request.length()>128||!fingerprint.matches("[a-f0-9]{64}"))throw new IllegalArgumentException("Invalid identity workflow identity");
        jdbc.update("INSERT INTO workflow_instance(workflow_id,kind,idempotency_scope,request_id,request_sha256,owner_user_id,actor_user_id,"
                +"resource_type,resource_id,resource_revision,status,payload_version,payload_json,result_version,result_json,result_sha256,created_at,updated_at,finished_at) "
                +"VALUES(?,?,?,?,?,?,?,'DETECTION_IDENTITY','GLOBAL',?,?,1,?,?,?,?,UTC_TIMESTAMP(6),UTC_TIMESTAMP(6),CASE WHEN ?='COMPLETED' THEN UTC_TIMESTAMP(6) ELSE NULL END)",
                UUID.randomUUID().toString(),kind,kind,request,fingerprint,actor,actor,revision,status,write(payload),result==null?null:1,result,result==null?null:sha(result),status);
    }
    private long audit(String kind,Long owner,Long actor,String task,String action,Long revision,String run,Long sequence,
                        String scope,String request,String previous,String digest,String payload) {
        String event=UUID.randomUUID().toString();
        jdbc.update("INSERT INTO audit_event(event_id,kind,owner_user_id,actor_user_id,resource_type,resource_id,run_id,sequence_no,request_scope,request_id,"
                +"action,revision,previous_sha256,event_sha256,payload_version,payload_json,occurred_at) "
                +"VALUES(?,?,?,?,'DETECTION_IDENTITY',?,?,?,?,?,?,?,?,?,1,?,UTC_TIMESTAMP(6))",event,kind,owner,actor,task,run,sequence,scope,request,action,revision,previous,digest,payload);
        return jdbc.queryForObject("SELECT id FROM audit_event WHERE event_id=?",Long.class,event);
    }
    /** utf8mb4_bin PAD SPACE treats only trailing ASCII spaces as insignificant. */
    public static String identityScope(String task,String role) {
        String canonical=pad(task);return sha(canonical.codePointCount(0,canonical.length())+":"+canonical+":"+pad(role));
    }
    private static String pad(String value) {int end=value.length();while(end>0&&value.charAt(end-1)==' ')end--;return value.substring(0,end);}
    public static String decimal(long value) {if(value<1)throw new IllegalArgumentException("Positive identity cursor required");return Long.toString(value);}
    private static Long positive(Long value) {return value!=null&&value>0?value:null;}
    private static Long number(Object value) {return value==null?null:value instanceof BigInteger integer?integer.longValueExact():((Number)value).longValue();}
    private void version(Map<String,Object> value) {if(!(value.get("payload_version") instanceof Number n)||n.intValue()!=1)throw new IllegalStateException("Unsupported identity payload version");}
    private String write(Object value) {try{return json.writeValueAsString(value);}catch(Exception error){throw new IllegalStateException("Identity payload encoding failed");}}
    private <T>T read(String value,Class<T> type) {try{return json.readValue(value,type);}catch(Exception error){throw new IllegalStateException("Stored identity payload differs from its closed protocol");}}
    public static String sha(String value) {try{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8)));}catch(Exception error){throw new IllegalStateException(error);}}
}
