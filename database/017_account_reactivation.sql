-- Additive restricted login + UC31 appeals. Explicit approval and backup required.
USE `smart_boarding_db`;
ALTER TABLE `admin_events`
    ADD COLUMN `user_visible_reason` VARCHAR(500) NULL DEFAULT NULL,
    ADD UNIQUE KEY `uq_admin_event_user` (`event_id`,`target_user_id`);
ALTER TABLE `auth_sessions`
    ADD COLUMN `session_scope` ENUM('normal','restricted') NOT NULL DEFAULT 'normal',
    ADD COLUMN `suspension_event_id` BIGINT UNSIGNED NULL DEFAULT NULL,
    ADD CONSTRAINT `fk_restricted_session_event` FOREIGN KEY (`suspension_event_id`) REFERENCES `admin_events` (`event_id`),
    ADD CONSTRAINT `chk_restricted_scope` CHECK (
        (session_scope='normal' AND suspension_event_id IS NULL)
        OR (session_scope='restricted' AND suspension_event_id IS NOT NULL AND remember_me=0
            AND expires_at<=DATE_ADD(created_at,INTERVAL 15 MINUTE)));
CREATE TABLE `reactivation_requests` (
    `request_id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `user_id` INT UNSIGNED NOT NULL,
    `suspension_event_id` BIGINT UNSIGNED NOT NULL,
    `message` VARCHAR(1000) NOT NULL,
    `status` ENUM('pending','approved','rejected') NOT NULL DEFAULT 'pending',
    `submitted_at` DATETIME(6) NOT NULL COMMENT 'UTC',
    `decided_by` INT UNSIGNED NULL DEFAULT NULL,
    `decision_note` VARCHAR(1000) NULL DEFAULT NULL,
    `decided_at` DATETIME(6) NULL DEFAULT NULL COMMENT 'UTC',
    `acknowledged_at` DATETIME(6) NULL DEFAULT NULL COMMENT 'UTC',
    `revision` INT UNSIGNED NOT NULL DEFAULT 0,
    PRIMARY KEY (`request_id`),
    UNIQUE KEY `uq_reactivation_suspension` (`user_id`,`suspension_event_id`),
    KEY `ix_reactivation_queue` (`status`,`submitted_at`,`request_id`),
    CONSTRAINT `fk_reactivation_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`user_id`),
    CONSTRAINT `fk_reactivation_suspension` FOREIGN KEY (`suspension_event_id`,`user_id`) REFERENCES `admin_events` (`event_id`,`target_user_id`),
    CONSTRAINT `fk_reactivation_admin` FOREIGN KEY (`decided_by`) REFERENCES `users` (`user_id`),
    CONSTRAINT `chk_reactivation_message` CHECK (CHAR_LENGTH(TRIM(message)) BETWEEN 1 AND 1000),
    CONSTRAINT `chk_reactivation_state` CHECK (
        (status='pending' AND decided_by IS NULL AND decided_at IS NULL AND decision_note IS NULL AND acknowledged_at IS NULL AND revision=0)
        OR (status IN ('approved','rejected') AND decided_by IS NOT NULL AND decided_at IS NOT NULL AND revision=1
            AND decided_at>=submitted_at AND (acknowledged_at IS NULL OR acknowledged_at>=decided_at)
            AND (status<>'rejected' OR (decision_note IS NOT NULL AND CHAR_LENGTH(TRIM(decision_note))>0))))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE `reactivation_events` (
    `event_id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `request_id` BIGINT UNSIGNED NOT NULL,
    `actor_id` INT UNSIGNED NOT NULL,
    `action` ENUM('submitted','approved','rejected','acknowledged') NOT NULL,
    `created_at` DATETIME(6) NOT NULL COMMENT 'UTC',
    PRIMARY KEY (`event_id`),
    UNIQUE KEY `uq_reactivation_event` (`request_id`,`action`),
    CONSTRAINT `fk_reactivation_event_request` FOREIGN KEY (`request_id`) REFERENCES `reactivation_requests` (`request_id`),
    CONSTRAINT `fk_reactivation_event_actor` FOREIGN KEY (`actor_id`) REFERENCES `users` (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
