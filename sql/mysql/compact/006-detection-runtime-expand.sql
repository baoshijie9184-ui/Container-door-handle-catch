-- Reviewed compact-domain extension. Source artifact only: integrate into the empty baseline.
-- No additional business table, compatibility view, live ALTER execution, or old-table fallback.
-- Root must extend ck_workflow_kind with the six DETECTION_* kinds below.
-- Root must extend ck_workflow_owner narrowly:
--   owner>0; OR DETECTION_WORKER owner=0/actor=NULL;
--   OR legacy DETECTION_TRANSFER owner=0/actor=NULL, legacy_source='detection_creation_object'.
-- Non-expiring worker/upload attempt tokens are permanent fences, not reclaimable leases.
-- ck_workflow_claim needs the non-lease branch for DETECTION_WORKER/DETECTION_TRANSFER,
-- and must retain a legacy CANCELLED creation job's lease when its old token was NULL.
-- Legacy DETECTION_COMMAND has no updated_at or terminal time: allow exact legacy NULLs.

ALTER TABLE workflow_instance
 ADD COLUMN detection_pair_task VARCHAR(128) COLLATE utf8mb4_bin GENERATED ALWAYS AS
   (CASE WHEN kind IN ('DETECTION_DISPATCH','DETECTION_WORKER') THEN resource_id ELSE NULL END) VIRTUAL,
 ADD COLUMN detection_pair_dispatch VARCHAR(64) COLLATE utf8mb4_bin GENERATED ALWAYS AS
   (CASE WHEN kind IN ('DETECTION_DISPATCH','DETECTION_WORKER') THEN run_id ELSE NULL END) VIRTUAL,
 ADD COLUMN detection_creation_task VARCHAR(128) COLLATE utf8mb4_bin GENERATED ALWAYS AS
   (CASE WHEN kind='DETECTION_CREATION' THEN resource_id ELSE NULL END) VIRTUAL,
 ADD COLUMN detection_transfer_command VARCHAR(36) COLLATE utf8mb4_bin GENERATED ALWAYS AS
   (CASE WHEN kind='DETECTION_TRANSFER' THEN resource_id ELSE NULL END) VIRTUAL,
 ADD COLUMN detection_transfer_index INT GENERATED ALWAYS AS
   (CASE WHEN kind='DETECTION_TRANSFER' THEN resource_revision ELSE NULL END) VIRTUAL,
 ADD UNIQUE KEY uk_detection_workflow_pair(kind,detection_pair_task,detection_pair_dispatch),
 ADD UNIQUE KEY uk_detection_creation_task(detection_creation_task),
 ADD UNIQUE KEY uk_detection_transfer_order(detection_transfer_command,detection_transfer_index),
 ADD KEY ix_detection_workflow_task(kind,resource_id,run_id,id),
 ADD KEY ix_detection_transfer_state(kind,resource_id,status,resource_revision),
 ADD CONSTRAINT ck_detection_task_workflow CHECK (
   kind NOT IN ('DETECTION_CREATION','DETECTION_COMMAND','DETECTION_DISPATCH','DETECTION_WORKER')
   OR (resource_type IS NOT NULL AND resource_type='DETECTION_TASK' AND resource_id IS NOT NULL
       AND CHAR_LENGTH(resource_id) BETWEEN 1 AND 128 AND run_id IS NOT NULL AND CHAR_LENGTH(run_id) BETWEEN 1 AND 64
       AND payload_version=1 AND parent_workflow_id IS NULL AND active_slot IS NULL)),
 ADD CONSTRAINT ck_detection_creation_workflow CHECK (kind<>'DETECTION_CREATION' OR (
   CHAR_LENGTH(workflow_id)=47 AND LEFT(workflow_id,11)='det-create:'
   AND owner_user_id>0 AND actor_user_id IS NOT NULL AND actor_user_id=owner_user_id
   AND idempotency_scope=CONCAT('OWNER:',owner_user_id) AND session_id IS NOT NULL
   AND JSON_LENGTH(payload_json)=7
   AND JSON_CONTAINS_PATH(payload_json,'all','$.actorUsername','$.actorRole','$.proposalId','$.previewJson',
       '$.bucketName','$.sourcePrefix','$.manifestSha256')=1
   AND JSON_TYPE(JSON_EXTRACT(payload_json,'$.actorUsername'))='STRING'
   AND CHAR_LENGTH(JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.actorUsername'))) BETWEEN 1 AND 50
   AND JSON_TYPE(JSON_EXTRACT(payload_json,'$.actorRole'))='STRING'
   AND JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.actorRole')) IN ('SUPERVISOR','INSPECTOR')
   AND JSON_TYPE(JSON_EXTRACT(payload_json,'$.proposalId'))='STRING'
   AND CHAR_LENGTH(JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.proposalId'))) BETWEEN 1 AND 128
   AND JSON_TYPE(JSON_EXTRACT(payload_json,'$.previewJson'))='STRING'
   AND JSON_VALID(JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.previewJson')))
   AND OCTET_LENGTH(JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.previewJson')))<=16777215
   AND request_sha256=SHA2(JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.previewJson')),256)
   AND ((JSON_TYPE(JSON_EXTRACT(payload_json,'$.bucketName'))='NULL'
       AND JSON_TYPE(JSON_EXTRACT(payload_json,'$.sourcePrefix'))='NULL'
       AND JSON_TYPE(JSON_EXTRACT(payload_json,'$.manifestSha256'))='NULL')
     OR (JSON_TYPE(JSON_EXTRACT(payload_json,'$.bucketName'))='STRING'
       AND CHAR_LENGTH(JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.bucketName'))) BETWEEN 1 AND 128
       AND JSON_TYPE(JSON_EXTRACT(payload_json,'$.sourcePrefix'))='STRING'
       AND CHAR_LENGTH(JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.sourcePrefix')))<=512
       AND JSON_TYPE(JSON_EXTRACT(payload_json,'$.manifestSha256'))='STRING'
       AND REGEXP_LIKE(JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.manifestSha256')),'^[a-f0-9]{64}$','c')))
   AND status IN ('PREPARING','UPLOADING','NEEDS_REVIEW','CANCELLED','QUEUED'))),
 ADD CONSTRAINT ck_detection_transfer_workflow CHECK (kind<>'DETECTION_TRANSFER' OR (
   resource_type IS NOT NULL AND resource_type='DETECTION_CREATION' AND resource_id IS NOT NULL
   AND CHAR_LENGTH(resource_id)=36 AND resource_revision IS NOT NULL AND resource_revision BETWEEN 0 AND 2147483647
   AND run_id IS NOT NULL AND CHAR_LENGTH(run_id)=36 AND request_id=run_id
   AND idempotency_scope=CONCAT('DETECTION_CREATION:',resource_id)
   AND payload_version=1 AND parent_workflow_id IS NULL AND lease_expires_at IS NULL
   AND JSON_LENGTH(payload_json)=7
   AND JSON_CONTAINS_PATH(payload_json,'all','$.objectKey','$.contentSha256','$.byteLength','$.contentType',
       '$.etag','$.objectVersion','$.ossRequestId')=1
   AND JSON_TYPE(JSON_EXTRACT(payload_json,'$.objectKey'))='STRING'
   AND CHAR_LENGTH(JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.objectKey'))) BETWEEN 1 AND 1024
   AND JSON_TYPE(JSON_EXTRACT(payload_json,'$.contentSha256'))='STRING'
   AND REGEXP_LIKE(JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.contentSha256')),'^[a-f0-9]{64}$','c')
   AND JSON_TYPE(JSON_EXTRACT(payload_json,'$.byteLength'))='INTEGER'
   AND CAST(JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.byteLength')) AS DECIMAL(20,0)) BETWEEN 0 AND 9223372036854775807
   AND JSON_TYPE(JSON_EXTRACT(payload_json,'$.contentType'))='STRING'
   AND CHAR_LENGTH(JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.contentType'))) BETWEEN 1 AND 64
   AND JSON_TYPE(JSON_EXTRACT(payload_json,'$.etag')) IN ('STRING','NULL')
   AND (JSON_TYPE(JSON_EXTRACT(payload_json,'$.etag'))='NULL' OR CHAR_LENGTH(JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.etag')))<=128)
   AND JSON_TYPE(JSON_EXTRACT(payload_json,'$.objectVersion')) IN ('STRING','NULL')
   AND (JSON_TYPE(JSON_EXTRACT(payload_json,'$.objectVersion'))='NULL' OR CHAR_LENGTH(JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.objectVersion')))<=1024)
   AND JSON_TYPE(JSON_EXTRACT(payload_json,'$.ossRequestId')) IN ('STRING','NULL')
   AND (JSON_TYPE(JSON_EXTRACT(payload_json,'$.ossRequestId'))='NULL' OR CHAR_LENGTH(JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.ossRequestId')))<=128)
   AND status IN ('PLANNED','UPLOADING','STORED')
   AND ((status='PLANNED' AND claim_token IS NULL) OR (status IN ('UPLOADING','STORED') AND claim_token IS NOT NULL)))),
 ADD CONSTRAINT ck_detection_review_workflow CHECK (kind<>'DETECTION_TRANSFER_REVIEW' OR (
   resource_type IS NOT NULL AND resource_type='DETECTION_CREATION' AND resource_id IS NOT NULL AND CHAR_LENGTH(resource_id)=36
   AND CHAR_LENGTH(workflow_id)=46 AND LEFT(workflow_id,10)='det-check:'
   AND owner_user_id>0 AND actor_user_id IS NOT NULL AND actor_user_id=owner_user_id
   AND idempotency_scope=CONCAT('OWNER:',owner_user_id) AND resource_revision IS NOT NULL AND resource_revision>=0
   AND payload_version=1 AND JSON_LENGTH(payload_json)=7
   AND JSON_CONTAINS_PATH(payload_json,'all','$.action','$.sourceCheckId','$.checkedCount','$.verifiedCount',
       '$.evidenceJson','$.evidenceSha256','$.completedRevision')=1
   AND JSON_TYPE(JSON_EXTRACT(payload_json,'$.action'))='STRING'
   AND JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.action')) IN ('CHECK','FINALIZE','ABANDON')
   AND (JSON_TYPE(JSON_EXTRACT(payload_json,'$.sourceCheckId'))='NULL'
     OR (JSON_TYPE(JSON_EXTRACT(payload_json,'$.sourceCheckId'))='STRING' AND CHAR_LENGTH(JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.sourceCheckId')))=36))
   AND JSON_TYPE(JSON_EXTRACT(payload_json,'$.checkedCount'))='INTEGER'
   AND JSON_TYPE(JSON_EXTRACT(payload_json,'$.verifiedCount'))='INTEGER'
   AND CAST(JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.checkedCount')) AS DECIMAL(20,0)) BETWEEN 0 AND 2147483647
   AND CAST(JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.verifiedCount')) AS DECIMAL(20,0)) BETWEEN 0 AND CAST(JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.checkedCount')) AS DECIMAL(20,0))
   AND ((JSON_TYPE(JSON_EXTRACT(payload_json,'$.evidenceJson'))='NULL' AND JSON_TYPE(JSON_EXTRACT(payload_json,'$.evidenceSha256'))='NULL')
     OR (JSON_TYPE(JSON_EXTRACT(payload_json,'$.evidenceJson'))='STRING' AND JSON_VALID(JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.evidenceJson')))
       AND JSON_TYPE(JSON_EXTRACT(payload_json,'$.evidenceSha256'))='STRING'
       AND JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.evidenceSha256'))=SHA2(JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.evidenceJson')),256)))
   AND (JSON_TYPE(JSON_EXTRACT(payload_json,'$.completedRevision'))='NULL'
     OR (JSON_TYPE(JSON_EXTRACT(payload_json,'$.completedRevision'))='INTEGER' AND CAST(JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.completedRevision')) AS DECIMAL(20,0)) BETWEEN 0 AND 9223372036854775807))
   AND status IN ('QUEUED','RUNNING','CANCELLED','COMPLETED','VERIFIED','INCOMPLETE','UNCONFIRMED'))),
 ADD CONSTRAINT ck_detection_command_workflow CHECK (kind<>'DETECTION_COMMAND' OR (
   owner_user_id>0 AND actor_user_id IS NOT NULL AND actor_user_id=owner_user_id
   AND idempotency_scope=CONCAT('OWNER:',owner_user_id) AND status='COMPLETED'
   AND payload_version=1 AND JSON_LENGTH(payload_json)=3
   AND JSON_CONTAINS_PATH(payload_json,'all','$.commandId','$.operation','$.proposalId')=1
   AND JSON_TYPE(JSON_EXTRACT(payload_json,'$.commandId'))='STRING'
   AND CHAR_LENGTH(JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.commandId'))) BETWEEN 1 AND 128
   AND workflow_id=CONCAT('det-cmd:',LEFT(SHA2(JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.commandId')),256),48))
   AND JSON_TYPE(JSON_EXTRACT(payload_json,'$.operation'))='STRING'
   AND JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.operation')) IN ('CREATE','RETRY')
   AND (JSON_TYPE(JSON_EXTRACT(payload_json,'$.proposalId'))='NULL'
     OR (JSON_TYPE(JSON_EXTRACT(payload_json,'$.proposalId'))='STRING' AND CHAR_LENGTH(JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.proposalId'))) BETWEEN 1 AND 128))
   AND result_json IS NOT NULL AND result_version=1 AND result_sha256=SHA2(result_json,256)
   AND claim_token IS NULL AND lease_expires_at IS NULL)),
 ADD CONSTRAINT ck_detection_dispatch_workflow CHECK (kind<>'DETECTION_DISPATCH' OR (
   owner_user_id>0 AND actor_user_id IS NOT NULL AND actor_user_id=owner_user_id
   AND idempotency_scope='DETECTION_DISPATCH' AND workflow_id=CONCAT('det-out:',LEFT(SHA2(request_id,256),48))
   AND payload_version=1 AND JSON_LENGTH(payload_json)=2
   AND JSON_CONTAINS_PATH(payload_json,'all','$.eventJson','$.actorRequestId')=1
   AND JSON_TYPE(JSON_EXTRACT(payload_json,'$.eventJson'))='STRING'
   AND JSON_VALID(JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.eventJson')))
   AND OCTET_LENGTH(JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.eventJson')))<=16777215
   AND JSON_TYPE(JSON_EXTRACT(payload_json,'$.actorRequestId'))='STRING'
   AND CHAR_LENGTH(JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.actorRequestId'))) BETWEEN 1 AND 128
   AND status IN ('PENDING','SENDING','SENT','NEEDS_REVIEW')
   AND ((status='SENDING' AND claim_token IS NOT NULL AND lease_expires_at IS NOT NULL)
     OR (status<>'SENDING' AND claim_token IS NULL AND lease_expires_at IS NULL)))),
 ADD CONSTRAINT ck_detection_worker_workflow CHECK (kind<>'DETECTION_WORKER' OR (
   owner_user_id=0 AND actor_user_id IS NULL AND idempotency_scope='DETECTION_WORKER'
   AND payload_version=1 AND JSON_LENGTH(payload_json)=1
   AND JSON_CONTAINS_PATH(payload_json,'all','$.schemaVersion')=1
   AND JSON_TYPE(JSON_EXTRACT(payload_json,'$.schemaVersion'))='INTEGER'
   AND JSON_EXTRACT(payload_json,'$.schemaVersion')=1
   AND status IN ('RUNNING','NEEDS_REVIEW','COMPLETED')
   AND claim_token IS NOT NULL AND lease_expires_at IS NULL AND fence>=1
   AND ((status='COMPLETED' AND result_version=1 AND result_json IS NOT NULL AND result_sha256=SHA2(result_json,256))
     OR (status<>'COMPLETED' AND result_version IS NULL AND result_json IS NULL AND result_sha256 IS NULL))));

-- The old owner table has no timestamps. Migration records exact legacySource and NULL times;
-- ck_runtime_updated may admit that exact marker only, not arbitrary untimed runtime payloads.
ALTER TABLE runtime_state
 ADD CONSTRAINT ck_detection_creation_owner CHECK (namespace<>'DETECTION_CREATION_OWNER' OR (
   owner_id>0 AND scope_key='' AND revision=0 AND session_id IS NULL AND state_key IS NULL
   AND state_code IS NULL AND current_ref IS NULL AND counter_value IS NULL
   AND ((payload_json IS NULL AND created_at IS NOT NULL AND updated_at IS NOT NULL)
     OR (payload_version=1 AND JSON_LENGTH(payload_json)=1
       AND JSON_TYPE(JSON_EXTRACT(payload_json,'$.legacySource'))='STRING'
       AND BINARY JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.legacySource'))=BINARY 'detection_creation_owner'
       AND created_at IS NULL AND updated_at IS NULL))));
