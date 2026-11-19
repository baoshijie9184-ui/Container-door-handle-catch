-- Run once after the 29-table compact baseline. Each ALTER is atomic in MySQL 8.
-- Existing token accounts/receipts retain their meaning and their original constraints.
ALTER TABLE llm_quota
    ADD COLUMN native_unit VARCHAR(8) NULL,
    ADD COLUMN native_limit DECIMAL(36,14) NULL,
    ADD COLUMN native_opening_used DECIMAL(36,14) NOT NULL DEFAULT 0,
    ADD COLUMN native_reserved DECIMAL(36,14) NOT NULL DEFAULT 0,
    ADD COLUMN native_spent DECIMAL(36,14) NOT NULL DEFAULT 0,
    ADD COLUMN native_rates JSON NULL,
    ADD CONSTRAINT ck_native_budget CHECK (
        (native_unit IS NULL AND native_limit IS NULL AND native_opening_used=0 AND native_reserved=0 AND native_spent=0 AND native_rates IS NULL)
        OR (native_unit IS NOT NULL AND native_unit IN ('USD','CNY','TOKEN') AND native_opening_used>=0 AND native_reserved>=0 AND native_spent>=0
            AND ((period_key IN ('NATIVE_POOL','NATIVE_MEMBER') AND native_limit IS NOT NULL AND native_limit>=0 AND native_rates IS NULL)
                OR (period_key='NATIVE_RATE' AND native_limit IS NULL AND native_rates IS NOT NULL))));

ALTER TABLE llm_usage
    ADD COLUMN native_reserved_delta DECIMAL(36,14) NULL,
    ADD COLUMN native_spent_delta DECIMAL(36,14) NULL,
    ADD COLUMN native_detail JSON NULL,
    ADD COLUMN native_command VARCHAR(128) NULL,
    ADD UNIQUE INDEX uq_native_budget_command(actor_user_id,native_command),
    DROP CHECK ck_llm_usage_type,
    DROP CHECK ck_llm_usage_origin,
    ADD CONSTRAINT ck_llm_usage_type CHECK (entry_type IN ('RESERVE','SETTLE','RELEASE','LIMIT_CHANGE','IMPORTED_USAGE','VOID',
        'NATIVE_HOLD','NATIVE_SETTLE','NATIVE_RELEASE','NATIVE_POLICY')),
    ADD CONSTRAINT ck_llm_usage_origin CHECK (
        (entry_type='IMPORTED_USAGE' AND root_operation_id IS NULL AND operation_id IS NULL AND source_audit_event_id IS NOT NULL AND actor_user_id IS NULL)
        OR (entry_type='NATIVE_POLICY' AND root_operation_id IS NULL AND operation_id IS NULL AND source_audit_event_id IS NULL AND actor_user_id IS NOT NULL)
        OR (entry_type NOT IN ('IMPORTED_USAGE','NATIVE_POLICY') AND root_operation_id IS NOT NULL AND operation_id IS NOT NULL AND source_audit_event_id IS NULL)),
    ADD CONSTRAINT ck_native_budget_entry CHECK (
        (entry_type NOT IN ('NATIVE_HOLD','NATIVE_SETTLE','NATIVE_RELEASE','NATIVE_POLICY') AND native_detail IS NULL AND native_command IS NULL AND native_reserved_delta IS NULL AND native_spent_delta IS NULL)
        OR (entry_type='NATIVE_POLICY' AND native_command IS NOT NULL AND native_detail IS NOT NULL AND native_reserved_delta IS NULL AND native_spent_delta IS NULL)
        OR (entry_type IN ('NATIVE_HOLD','NATIVE_SETTLE','NATIVE_RELEASE') AND native_detail IS NOT NULL AND native_command IS NULL AND native_reserved_delta IS NOT NULL AND native_spent_delta IS NOT NULL
            AND ((entry_type='NATIVE_HOLD' AND native_reserved_delta>0 AND native_spent_delta=0)
                OR (entry_type='NATIVE_SETTLE' AND native_reserved_delta<0 AND native_spent_delta>=0)
                OR (entry_type='NATIVE_RELEASE' AND native_reserved_delta<0 AND native_spent_delta=0))));
