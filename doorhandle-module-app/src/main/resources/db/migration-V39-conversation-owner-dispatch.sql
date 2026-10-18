-- Additive dispatch index. Preserve after rollback; no input or execution state is rewritten.
CREATE INDEX idx_conversation_input_dispatch_owner ON agent_conversation_input (status,user_id,id);
