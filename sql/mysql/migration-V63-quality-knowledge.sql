-- Additive. Apply before APP_KNOWLEDGE_ENABLED=true; never backfill demonstration content.
CREATE TABLE IF NOT EXISTS quality_knowledge_owner (owner_user_id BIGINT NOT NULL PRIMARY KEY)
 ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE IF NOT EXISTS quality_knowledge_document (
 id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, document_id VARCHAR(64) NOT NULL,
 owner_user_id BIGINT NOT NULL, title VARCHAR(180) NOT NULL, filename VARCHAR(255) NOT NULL,
 visibility VARCHAR(16) NOT NULL, lifecycle VARCHAR(16) NOT NULL DEFAULT 'ACTIVE',
 current_version INT NOT NULL, revision INT NOT NULL DEFAULT 1, created_at DATETIME(6) NOT NULL, updated_at DATETIME(6) NOT NULL,
 UNIQUE KEY uk_knowledge_document(document_id), KEY idx_knowledge_owner(owner_user_id,lifecycle,id),
 KEY idx_knowledge_visibility(visibility,lifecycle,id),
 CHECK(visibility IN ('PRIVATE','ENTERPRISE')), CHECK(lifecycle IN ('ACTIVE','ARCHIVED'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE IF NOT EXISTS quality_knowledge_revision (
 id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, document_id VARCHAR(64) NOT NULL, version INT NOT NULL,
 content_text MEDIUMTEXT NOT NULL, content_sha256 CHAR(64) NOT NULL, media_type VARCHAR(120) NOT NULL,
 title VARCHAR(180) NOT NULL, filename VARCHAR(255) NOT NULL, source_bytes MEDIUMBLOB NOT NULL, source_sha256 CHAR(64) NOT NULL, byte_length BIGINT NOT NULL,
 index_state VARCHAR(16) NOT NULL, chunk_count INT NOT NULL, creator_user_id BIGINT NOT NULL, created_at DATETIME(6) NOT NULL,
 UNIQUE KEY uk_knowledge_revision(document_id,version),
 CONSTRAINT fk_knowledge_revision_document FOREIGN KEY(document_id) REFERENCES quality_knowledge_document(document_id),
 CHECK(index_state IN ('READY','EMPTY')), CHECK(chunk_count>=0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE IF NOT EXISTS quality_knowledge_chunk (
 id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, document_id VARCHAR(64) NOT NULL, version INT NOT NULL,
 ordinal_no INT NOT NULL, locator VARCHAR(100) NOT NULL, content_text TEXT NOT NULL,
 UNIQUE KEY uk_knowledge_chunk(document_id,version,ordinal_no),
 CONSTRAINT fk_knowledge_chunk_revision FOREIGN KEY(document_id,version) REFERENCES quality_knowledge_revision(document_id,version)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE IF NOT EXISTS quality_knowledge_command (
 actor_user_id BIGINT NOT NULL, request_id VARCHAR(64) NOT NULL, request_sha256 CHAR(64) NOT NULL,
 document_id VARCHAR(64) NOT NULL, version INT NOT NULL, action_name VARCHAR(24) NOT NULL, created_at DATETIME(6) NOT NULL,
 PRIMARY KEY(actor_user_id,request_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE IF NOT EXISTS quality_knowledge_audit (
 id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, document_id VARCHAR(64) NOT NULL, version INT NOT NULL,
 actor_user_id BIGINT NOT NULL, action_name VARCHAR(24) NOT NULL, content_sha256 CHAR(64), created_at DATETIME(6) NOT NULL,
 KEY idx_knowledge_audit(document_id,id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
