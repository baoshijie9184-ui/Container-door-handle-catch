-- Provider observations are append-only, per model; no seed quota, invented consumption, or pooled 1M grant.
CREATE TABLE IF NOT EXISTS agent_model_budget (
 model_id VARCHAR(180) NOT NULL PRIMARY KEY, total_tokens BIGINT NULL, warning_percent INT NOT NULL DEFAULT 80,
 free_only BOOLEAN NOT NULL DEFAULT TRUE, expires_at DATETIME(6) NULL, version INT NOT NULL DEFAULT 1,
 updated_by BIGINT NULL, updated_at DATETIME(6) NOT NULL,
 CHECK(total_tokens IS NULL OR total_tokens>=0), CHECK(warning_percent BETWEEN 1 AND 100)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE IF NOT EXISTS agent_model_budget_attempt (
 id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, attempt_id VARCHAR(64) NOT NULL, model_id VARCHAR(180) NOT NULL,
 status VARCHAR(16) NOT NULL, input_tokens BIGINT NULL, output_tokens BIGINT NULL, cached_tokens BIGINT NULL,
 started_at DATETIME(6) NOT NULL, finished_at DATETIME(6) NULL,
 UNIQUE KEY uk_budget_attempt(attempt_id), KEY idx_budget_model_time(model_id,started_at,id),
 CHECK(status IN ('STARTED','COMPLETED','FAILED','CANCELLED')),
 CHECK(input_tokens IS NULL OR input_tokens>=0), CHECK(output_tokens IS NULL OR output_tokens>=0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE IF NOT EXISTS agent_model_budget_observation (
 id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, model_id VARCHAR(180) NOT NULL,
 remaining_tokens BIGINT NOT NULL, observed_at DATETIME(6) NOT NULL, source_note VARCHAR(500) NOT NULL,
 actor_user_id BIGINT NOT NULL, request_id VARCHAR(64) NOT NULL, request_sha256 CHAR(64) NOT NULL, created_at DATETIME(6) NOT NULL,
 UNIQUE KEY uk_budget_observation_request(actor_user_id,request_id), KEY idx_budget_observation(model_id,observed_at,id),
 CHECK(remaining_tokens>=0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE IF NOT EXISTS agent_model_budget_audit (
 id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, model_id VARCHAR(180) NOT NULL, actor_user_id BIGINT NOT NULL,
 action_name VARCHAR(24) NOT NULL, version INT NOT NULL, detail_json JSON NOT NULL, created_at DATETIME(6) NOT NULL,
 KEY idx_budget_audit(model_id,id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
