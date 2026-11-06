-- Source artifact only. Run on the admitted ECS against a fresh compact target.
-- The orchestrator holds an independent READ lock on the entire frozen source.
-- Preserve source DATETIME values as recorded; no import clock replaces an unknown source time.
-- Render __SOURCE_SCHEMA__ only after validating the schema identifier.
CREATE TEMPORARY TABLE compact_support_guard(valid INT NOT NULL CHECK(valid=1)) ENGINE=InnoDB;
INSERT INTO compact_support_guard SELECT IF(DATABASE() IS NOT NULL AND BINARY DATABASE()<>BINARY '__SOURCE_SCHEMA__' AND @@FOREIGN_KEY_CHECKS=1,1,0);
START TRANSACTION;
INSERT INTO compact_support_guard SELECT IF(COUNT(*)=1,1,0) FROM information_schema.tables WHERE table_schema='__SOURCE_SCHEMA__' AND table_name='agent_research_storage_owner' AND table_type='BASE TABLE' AND engine='InnoDB';
INSERT INTO compact_support_guard SELECT IF(COUNT(*)=2,1,0) FROM information_schema.columns WHERE table_schema='__SOURCE_SCHEMA__' AND table_name='agent_research_storage_owner';
INSERT INTO compact_support_guard SELECT IF(COUNT(*)=1,1,0) FROM information_schema.columns WHERE table_schema='__SOURCE_SCHEMA__' AND table_name='agent_research_storage_owner' AND column_name='user_id' AND BINARY column_type=BINARY 'bigint' AND is_nullable='NO';
INSERT INTO compact_support_guard SELECT IF(COUNT(*)=1,1,0) FROM information_schema.columns WHERE table_schema='__SOURCE_SCHEMA__' AND table_name='agent_research_storage_owner' AND column_name='created_at' AND BINARY column_type=BINARY 'datetime(6)' AND is_nullable='NO';
CREATE TEMPORARY TABLE `compact_support_agent_research_storage_owner`(source_key VARCHAR(512) COLLATE utf8mb4_bin PRIMARY KEY,source_json LONGTEXT NOT NULL,source_sha256 CHAR(64) NOT NULL) ENGINE=InnoDB;
INSERT INTO `compact_support_agent_research_storage_owner` SELECT CAST(JSON_ARRAY(s.`user_id`) AS CHAR CHARACTER SET utf8mb4),CAST(JSON_OBJECT('user_id',s.`user_id`,'created_at',s.`created_at`) AS CHAR CHARACTER SET utf8mb4),SHA2(CAST(JSON_OBJECT('user_id',s.`user_id`,'created_at',s.`created_at`) AS CHAR CHARACTER SET utf8mb4),256) FROM `__SOURCE_SCHEMA__`.`agent_research_storage_owner` s;
INSERT INTO compact_support_guard SELECT IF(COUNT(*)=1,1,0) FROM information_schema.tables WHERE table_schema='__SOURCE_SCHEMA__' AND table_name='agent_skill_download_owner' AND table_type='BASE TABLE' AND engine='InnoDB';
INSERT INTO compact_support_guard SELECT IF(COUNT(*)=1,1,0) FROM information_schema.columns WHERE table_schema='__SOURCE_SCHEMA__' AND table_name='agent_skill_download_owner';
INSERT INTO compact_support_guard SELECT IF(COUNT(*)=1,1,0) FROM information_schema.columns WHERE table_schema='__SOURCE_SCHEMA__' AND table_name='agent_skill_download_owner' AND column_name='owner_user_id' AND BINARY column_type=BINARY 'bigint' AND is_nullable='NO';
CREATE TEMPORARY TABLE `compact_support_agent_skill_download_owner`(source_key VARCHAR(512) COLLATE utf8mb4_bin PRIMARY KEY,source_json LONGTEXT NOT NULL,source_sha256 CHAR(64) NOT NULL) ENGINE=InnoDB;
INSERT INTO `compact_support_agent_skill_download_owner` SELECT CAST(JSON_ARRAY(s.`owner_user_id`) AS CHAR CHARACTER SET utf8mb4),CAST(JSON_OBJECT('owner_user_id',s.`owner_user_id`) AS CHAR CHARACTER SET utf8mb4),SHA2(CAST(JSON_OBJECT('owner_user_id',s.`owner_user_id`) AS CHAR CHARACTER SET utf8mb4),256) FROM `__SOURCE_SCHEMA__`.`agent_skill_download_owner` s;
INSERT INTO compact_support_guard SELECT IF(COUNT(*)=0,1,0) FROM runtime_state WHERE namespace='RESEARCH_STORAGE';
INSERT INTO runtime_state(namespace,owner_id,scope_key,revision,created_at,updated_at) SELECT 'RESEARCH_STORAGE',s.`user_id`,'',0,s.created_at,NULL FROM `__SOURCE_SCHEMA__`.`agent_research_storage_owner` s;
INSERT INTO compact_support_guard SELECT IF((SELECT COUNT(*) FROM runtime_state WHERE namespace='RESEARCH_STORAGE')=(SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.`agent_research_storage_owner`),1,0);
INSERT INTO compact_support_guard SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.`agent_research_storage_owner` s LEFT JOIN runtime_state t ON t.namespace='RESEARCH_STORAGE' AND t.owner_id=s.`user_id` AND t.scope_key='' WHERE t.owner_id IS NULL OR t.revision<>0 OR t.updated_at IS NOT NULL OR NOT(t.created_at<=>s.created_at);
INSERT INTO compact_support_guard SELECT IF(COUNT(*)=0,1,0) FROM runtime_state WHERE namespace='SKILL_DOWNLOAD';
INSERT INTO runtime_state(namespace,owner_id,scope_key,revision,created_at,updated_at) SELECT 'SKILL_DOWNLOAD',s.`owner_user_id`,'',0,NULL,NULL FROM `__SOURCE_SCHEMA__`.`agent_skill_download_owner` s;
INSERT INTO compact_support_guard SELECT IF((SELECT COUNT(*) FROM runtime_state WHERE namespace='SKILL_DOWNLOAD')=(SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.`agent_skill_download_owner`),1,0);
INSERT INTO compact_support_guard SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.`agent_skill_download_owner` s LEFT JOIN runtime_state t ON t.namespace='SKILL_DOWNLOAD' AND t.owner_id=s.`owner_user_id` AND t.scope_key='' WHERE t.owner_id IS NULL OR t.revision<>0 OR t.updated_at IS NOT NULL OR NOT(t.created_at<=>NULL);
INSERT INTO compact_support_guard SELECT IF((SELECT COUNT(*) FROM `compact_support_agent_research_storage_owner`)=(SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.`agent_research_storage_owner`),1,0);
INSERT INTO compact_support_guard SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.`agent_research_storage_owner` s LEFT JOIN `compact_support_agent_research_storage_owner` p ON BINARY p.source_key=BINARY CAST(JSON_ARRAY(s.`user_id`) AS CHAR CHARACTER SET utf8mb4) WHERE p.source_key IS NULL OR BINARY p.source_sha256<>BINARY SHA2(CAST(JSON_OBJECT('user_id',s.`user_id`,'created_at',s.`created_at`) AS CHAR CHARACTER SET utf8mb4),256);
INSERT INTO compact_support_guard SELECT IF((SELECT COUNT(*) FROM `compact_support_agent_skill_download_owner`)=(SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.`agent_skill_download_owner`),1,0);
INSERT INTO compact_support_guard SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.`agent_skill_download_owner` s LEFT JOIN `compact_support_agent_skill_download_owner` p ON BINARY p.source_key=BINARY CAST(JSON_ARRAY(s.`owner_user_id`) AS CHAR CHARACTER SET utf8mb4) WHERE p.source_key IS NULL OR BINARY p.source_sha256<>BINARY SHA2(CAST(JSON_OBJECT('owner_user_id',s.`owner_user_id`) AS CHAR CHARACTER SET utf8mb4),256);
COMMIT;
DROP TEMPORARY TABLE `compact_support_agent_research_storage_owner`;
DROP TEMPORARY TABLE `compact_support_agent_skill_download_owner`;
DROP TEMPORARY TABLE compact_support_guard;
