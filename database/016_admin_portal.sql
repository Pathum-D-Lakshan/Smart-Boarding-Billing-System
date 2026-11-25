-- Additive Admin controls. Run once only after explicit approval and fresh backup.
USE `smart_boarding_db`;
ALTER TABLE `users`
    ADD COLUMN `admin_suspended` BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN `admin_revision` INT UNSIGNED NOT NULL DEFAULT 0,
    ADD CONSTRAINT `chk_users_admin_suspension` CHECK (admin_suspended IN (0,1) AND (role <> 'admin' OR admin_suspended=0)),
    ADD INDEX `ix_users_admin_status` (`role`,`admin_suspended`,`is_active`,`created_at`,`user_id`);
ALTER TABLE `boardings`
    ADD COLUMN `admin_hidden` BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN `admin_revision` INT UNSIGNED NOT NULL DEFAULT 0,
    ADD CONSTRAINT `chk_boardings_admin_hidden` CHECK (admin_hidden IN (0,1)),
    ADD INDEX `ix_boardings_admin_visibility` (`status`,`admin_hidden`,`created_at`,`boarding_id`);
CREATE TABLE `admin_events` (
    `event_id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `actor_id` INT UNSIGNED NOT NULL,
    `target_user_id` INT UNSIGNED DEFAULT NULL,
    `boarding_id` INT UNSIGNED DEFAULT NULL,
    `action` ENUM('user_suspended','user_reactivated','listing_hidden','listing_restored','admin_provisioned') NOT NULL,
    `previous_state` VARCHAR(16) DEFAULT NULL,
    `new_state` VARCHAR(16) NOT NULL,
    `revision` INT UNSIGNED NOT NULL,
    `reason` VARCHAR(500) NOT NULL,
    `created_at` DATETIME(6) NOT NULL COMMENT 'UTC',
    PRIMARY KEY (`event_id`),
    UNIQUE KEY `uq_admin_user_revision` (`target_user_id`,`revision`),
    UNIQUE KEY `uq_admin_boarding_revision` (`boarding_id`,`revision`),
    KEY `ix_admin_events_recent` (`created_at`,`event_id`),
    CONSTRAINT `fk_admin_event_actor` FOREIGN KEY (`actor_id`) REFERENCES `users` (`user_id`),
    CONSTRAINT `fk_admin_event_user` FOREIGN KEY (`target_user_id`) REFERENCES `users` (`user_id`),
    CONSTRAINT `fk_admin_event_boarding` FOREIGN KEY (`boarding_id`) REFERENCES `boardings` (`boarding_id`),
    CONSTRAINT `chk_admin_event_target` CHECK (
        (target_user_id IS NOT NULL AND boarding_id IS NULL AND action IN ('user_suspended','user_reactivated','admin_provisioned'))
        OR (target_user_id IS NULL AND boarding_id IS NOT NULL AND action IN ('listing_hidden','listing_restored'))),
    CONSTRAINT `chk_admin_event_revision` CHECK (revision>0 OR action='admin_provisioned'),
    CONSTRAINT `chk_admin_event_reason` CHECK (CHAR_LENGTH(TRIM(reason))>0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
