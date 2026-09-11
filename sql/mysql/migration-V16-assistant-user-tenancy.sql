-- Apply after the chat project/session migrations. The migration aborts instead
-- of assigning orphaned assistant data to an arbitrary user.
ALTER TABLE `chat_project` ADD COLUMN `user_id` BIGINT NULL AFTER `username`;
ALTER TABLE `chat_session` ADD COLUMN `user_id` BIGINT NULL AFTER `username`;

UPDATE `chat_project` p
JOIN `users` u ON u.`username` = p.`username`
SET p.`user_id` = u.`id`
WHERE p.`user_id` IS NULL;

UPDATE `chat_session` s
JOIN `users` u ON u.`username` = s.`username`
SET s.`user_id` = u.`id`
WHERE s.`user_id` IS NULL;

DROP PROCEDURE IF EXISTS `assert_assistant_tenant_backfill`;
DELIMITER $$
CREATE PROCEDURE `assert_assistant_tenant_backfill`()
BEGIN
    IF EXISTS (SELECT 1 FROM `chat_project` WHERE `user_id` IS NULL)
       OR EXISTS (SELECT 1 FROM `chat_session` WHERE `user_id` IS NULL) THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'Assistant tenancy backfill failed: unmatched username';
    END IF;
END$$
DELIMITER ;
CALL `assert_assistant_tenant_backfill`();
DROP PROCEDURE `assert_assistant_tenant_backfill`;

ALTER TABLE `chat_project`
    MODIFY COLUMN `user_id` BIGINT NOT NULL,
    ADD KEY `idx_chat_project_tenant_sort_created` (`user_id`, `sort_order`, `created_at` DESC),
    ADD CONSTRAINT `fk_chat_project_tenant_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE ON UPDATE RESTRICT;

ALTER TABLE `chat_session`
    MODIFY COLUMN `user_id` BIGINT NOT NULL,
    ADD KEY `idx_chat_session_tenant_status_updated` (`user_id`, `status`, `updated_at` DESC),
    ADD KEY `idx_chat_session_tenant_status_pinned_updated` (`user_id`, `status`, `pinned` DESC, `updated_at` DESC),
    ADD CONSTRAINT `fk_chat_session_tenant_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE ON UPDATE RESTRICT;
