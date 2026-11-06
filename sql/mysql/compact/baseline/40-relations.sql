-- Cross-table relations for the compact 29-table schema; source-only build until ECS validation.

-- core-relations.sql
-- Core12 FK draft. Retains old referential actions; new stricter relationships are comments until audited.

ALTER TABLE employee ADD CONSTRAINT fk_employee_department FOREIGN KEY(department_id) REFERENCES organization_department(id) ON DELETE RESTRICT;

ALTER TABLE users ADD CONSTRAINT fk_users_employee FOREIGN KEY(employee_id) REFERENCES employee(id) ON DELETE RESTRICT;

ALTER TABLE device_management ADD CONSTRAINT `fk_device_employee` FOREIGN KEY (`employee_id`) REFERENCES `employee` (`id`) ON DELETE SET NULL;

ALTER TABLE device_usage ADD CONSTRAINT `fk_usage_device` FOREIGN KEY (`device_id`) REFERENCES `device_management` (`id`) ON DELETE CASCADE;

ALTER TABLE device_usage ADD CONSTRAINT `fk_usage_employee` FOREIGN KEY (`employee_id`) REFERENCES `employee` (`id`) ON DELETE CASCADE;

ALTER TABLE device_alert ADD CONSTRAINT `fk_capture_alert_device` FOREIGN KEY (`device_id`) REFERENCES `device_management` (`id`) ON DELETE SET NULL;

ALTER TABLE detection_task ADD CONSTRAINT `fk_detection_task_model` FOREIGN KEY (`model_id`) REFERENCES `model_management` (`model_id`) ON DELETE SET NULL ON UPDATE CASCADE;

ALTER TABLE historical_detection_summary ADD CONSTRAINT `fk_image_detection_model` FOREIGN KEY (`model_id`) REFERENCES `model_management` (`model_id`) ON DELETE SET NULL ON UPDATE CASCADE;

-- Install relations after candidate data has been copied and checked. Preserve original session deletion/update actions.
ALTER TABLE detection_task ADD CONSTRAINT fk_detection_task_session FOREIGN KEY(session_id) REFERENCES chat_session(session_id) ON DELETE SET NULL ON UPDATE CASCADE;

-- Proposed after source orphan audit: detection_input.work_unit_id -> detection_work_unit.work_unit_id (RESTRICT). Old source had no FK.

-- Proposed after source orphan audit: quality_report.task_id -> detection_task.task_id, quality_report.previous_report_id -> quality_report.report_id. Never discard orphan rows to add these.

-- Cross-file content relation: detection_input(content_asset_id,content_version) -> content_revision(asset_id,version), ON DELETE RESTRICT. Verify shared types/key before assembly.

-- Account binding deletion/id/history protection is declared in 36-identity-guards.sql.

-- content-relations.sql
-- Explicit full unique endpoints; retained content deliberately has no deleting-owner/model FK.
ALTER TABLE content_revision ADD CONSTRAINT fk_content_revision_asset FOREIGN KEY(asset_id,asset_kind) REFERENCES content_asset(asset_id,asset_kind);
ALTER TABLE content_chunk ADD CONSTRAINT fk_content_chunk_revision FOREIGN KEY(asset_id,version) REFERENCES content_revision(asset_id,version);
ALTER TABLE content_link ADD CONSTRAINT fk_content_link_revision FOREIGN KEY(asset_id,asset_version) REFERENCES content_revision(asset_id,version);
ALTER TABLE content_asset ADD CONSTRAINT fk_content_current_revision FOREIGN KEY(asset_id,current_version) REFERENCES content_revision(asset_id,version);
ALTER TABLE content_asset ADD CONSTRAINT fk_content_published_revision FOREIGN KEY(asset_id,published_version) REFERENCES content_revision(asset_id,version);

-- compact28-agent-relations.sql
ALTER TABLE chat_project
 ADD CONSTRAINT fk_chat_project_user FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE ON UPDATE RESTRICT,
 ADD CONSTRAINT fk_chat_project_username FOREIGN KEY(username) REFERENCES users(username) ON DELETE CASCADE ON UPDATE CASCADE;
ALTER TABLE chat_session
 ADD CONSTRAINT fk_chat_session_user FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE ON UPDATE RESTRICT,
 ADD CONSTRAINT fk_chat_session_username FOREIGN KEY(username) REFERENCES users(username) ON DELETE CASCADE ON UPDATE CASCADE,
 ADD CONSTRAINT fk_chat_session_project FOREIGN KEY(project_id) REFERENCES chat_project(project_id) ON DELETE SET NULL ON UPDATE RESTRICT;
ALTER TABLE chat_message
 ADD CONSTRAINT fk_chat_message_session FOREIGN KEY(session_id) REFERENCES chat_session(session_id) ON DELETE CASCADE ON UPDATE CASCADE;
-- Original V44/V45/V66 evidence identities are retained independently of live
-- messages/users/sessions. They must not acquire deleting or re-keying parent FKs.
-- Current message projections are validated by their transactional write paths.
ALTER TABLE chat_message
 ADD CONSTRAINT fk_chat_execution_evidence FOREIGN KEY(execution_owner_user_id,execution_evidence_id) REFERENCES audit_event(owner_user_id,id) ON DELETE RESTRICT ON UPDATE RESTRICT,
 ADD CONSTRAINT fk_chat_snapshot_evidence FOREIGN KEY(snapshot_owner_user_id,snapshot_evidence_id) REFERENCES audit_event(owner_user_id,id) ON DELETE RESTRICT ON UPDATE RESTRICT,
 ADD CONSTRAINT fk_chat_context_evidence FOREIGN KEY(context_owner_user_id,context_evidence_id) REFERENCES audit_event(owner_user_id,id) ON DELETE RESTRICT ON UPDATE RESTRICT;
ALTER TABLE llm_quota
 ADD CONSTRAINT fk_llm_quota_user FOREIGN KEY(owner_user_id) REFERENCES users(id) ON DELETE RESTRICT ON UPDATE RESTRICT;
ALTER TABLE workflow_instance
 ADD CONSTRAINT fk_workflow_quota_decider FOREIGN KEY(decider_user_id) REFERENCES users(id) ON DELETE RESTRICT ON UPDATE RESTRICT;
-- Only LEGACY_CHAT_ACTION owns this ordinary reference, enforced by 39-workflow-guards.sql.
-- Session deletion and key changes preserve the old chat_pending_action lifecycle.
ALTER TABLE workflow_instance
 ADD CONSTRAINT fk_workflow_legacy_chat_session FOREIGN KEY(chat_action_session_id) REFERENCES chat_session(session_id) ON DELETE CASCADE ON UPDATE CASCADE;
ALTER TABLE llm_usage
 ADD CONSTRAINT fk_llm_usage_account FOREIGN KEY(account_id) REFERENCES llm_quota(id) ON DELETE RESTRICT ON UPDATE RESTRICT,
 ADD CONSTRAINT fk_llm_usage_source_audit FOREIGN KEY(source_audit_event_id) REFERENCES audit_event(id) ON DELETE RESTRICT ON UPDATE RESTRICT,
 ADD CONSTRAINT fk_llm_usage_root FOREIGN KEY(root_operation_id) REFERENCES workflow_instance(id) ON DELETE RESTRICT ON UPDATE RESTRICT,
 ADD CONSTRAINT fk_llm_usage_operation FOREIGN KEY(operation_id) REFERENCES workflow_instance(id) ON DELETE RESTRICT ON UPDATE RESTRICT;

ALTER TABLE audit_event
 ADD CONSTRAINT fk_audit_journal_run FOREIGN KEY(owner_user_id,journal_run_id) REFERENCES agent_run(user_id,run_id) ON DELETE RESTRICT ON UPDATE RESTRICT;

ALTER TABLE audit_event
 ADD CONSTRAINT fk_audit_research_export_run FOREIGN KEY(owner_user_id,research_export_run_id) REFERENCES agent_run(user_id,run_id) ON DELETE RESTRICT ON UPDATE RESTRICT;

-- V3 model operation logs follow their model lifecycle, including PK changes.
-- Other audit kinds have a NULL reference and do not participate in this cascade.
ALTER TABLE audit_event
 ADD CONSTRAINT fk_audit_detection_model FOREIGN KEY(detection_model_id) REFERENCES model_management(model_id) ON DELETE CASCADE ON UPDATE CASCADE;

ALTER TABLE detection_input ADD CONSTRAINT fk_detection_input_content FOREIGN KEY(content_asset_id,content_version) REFERENCES content_revision(asset_id,version) ON DELETE RESTRICT ON UPDATE RESTRICT;
