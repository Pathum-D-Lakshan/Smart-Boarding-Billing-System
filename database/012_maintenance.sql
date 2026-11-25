-- Additive only. No changes to existing tenancy, rooms, expense or payment records.
USE `smart_boarding_db`;

CREATE TABLE `maintenance_requests` (
    `maintenance_id` INT UNSIGNED NOT NULL AUTO_INCREMENT,
    `maintenance_reference` VARCHAR(44) NOT NULL,
    `boarding_id` INT UNSIGNED NOT NULL,
    `tenancy_id` INT UNSIGNED DEFAULT NULL,
    `reported_by_user_id` INT UNSIGNED NOT NULL,
    `reporter_role` ENUM('owner','student') NOT NULL,
    `reporter_name` VARCHAR(150) NOT NULL,
    `boarding_label` VARCHAR(255) NOT NULL,
    `room_id` INT UNSIGNED DEFAULT NULL,
    `room_label` VARCHAR(100) DEFAULT NULL,
    `issue_title` VARCHAR(150) NOT NULL,
    `description` VARCHAR(1000) NOT NULL,
    `priority` ENUM('low','medium','high') NOT NULL DEFAULT 'medium',
    `status` ENUM('pending','in_progress','resolved') NOT NULL DEFAULT 'pending',
    `owner_note` VARCHAR(1000) DEFAULT NULL,
    `resolution_note` VARCHAR(1000) DEFAULT NULL,
    `expense_id` INT UNSIGNED DEFAULT NULL,
    `request_key` CHAR(32) NOT NULL,
    `revision` INT UNSIGNED NOT NULL DEFAULT 0,
    `created_at` DATETIME(6) NOT NULL COMMENT 'UTC',
    `updated_at` DATETIME(6) NOT NULL COMMENT 'UTC',
    `status_changed_at` DATETIME(6) NOT NULL COMMENT 'UTC',
    `status_changed_by` INT UNSIGNED NOT NULL,
    `started_at` DATETIME(6) DEFAULT NULL COMMENT 'UTC',
    `started_by` INT UNSIGNED DEFAULT NULL,
    `resolved_at` DATETIME(6) DEFAULT NULL COMMENT 'UTC',
    `resolved_by` INT UNSIGNED DEFAULT NULL,
    PRIMARY KEY (`maintenance_id`),
    UNIQUE KEY `uq_maintenance_reference` (`maintenance_reference`),
    UNIQUE KEY `uq_maintenance_request` (`reported_by_user_id`,`request_key`),
    UNIQUE KEY `uq_maintenance_expense` (`expense_id`),
    KEY `idx_maintenance_owner` (`boarding_id`,`status`,`created_at`,`maintenance_id`),
    KEY `idx_maintenance_reporter` (`reported_by_user_id`,`reporter_role`,`created_at`),
    CONSTRAINT `fk_maintenance_boarding` FOREIGN KEY (`boarding_id`) REFERENCES `boardings` (`boarding_id`),
    CONSTRAINT `fk_maintenance_tenancy` FOREIGN KEY (`tenancy_id`) REFERENCES `tenancies` (`tenancy_id`),
    CONSTRAINT `fk_maintenance_reporter` FOREIGN KEY (`reported_by_user_id`) REFERENCES `users` (`user_id`),
    CONSTRAINT `fk_maintenance_room` FOREIGN KEY (`room_id`) REFERENCES `rooms` (`room_id`),
    CONSTRAINT `fk_maintenance_expense` FOREIGN KEY (`expense_id`) REFERENCES `expenses` (`expense_id`),
    CONSTRAINT `fk_maintenance_actor` FOREIGN KEY (`status_changed_by`) REFERENCES `users` (`user_id`),
    CONSTRAINT `fk_maintenance_starter` FOREIGN KEY (`started_by`) REFERENCES `users` (`user_id`),
    CONSTRAINT `fk_maintenance_resolver` FOREIGN KEY (`resolved_by`) REFERENCES `users` (`user_id`),
    CONSTRAINT `chk_maintenance_reporter` CHECK ((reporter_role='student' AND tenancy_id IS NOT NULL)
        OR (reporter_role='owner' AND tenancy_id IS NULL)),
    CONSTRAINT `chk_maintenance_location` CHECK ((room_id IS NULL AND room_label IS NULL)
        OR (room_id IS NOT NULL AND room_label IS NOT NULL)),
    CONSTRAINT `chk_maintenance_content` CHECK (CHAR_LENGTH(TRIM(issue_title))>0 AND CHAR_LENGTH(TRIM(description))>0),
    CONSTRAINT `chk_maintenance_started` CHECK ((started_at IS NULL AND started_by IS NULL)
        OR (started_at IS NOT NULL AND started_by IS NOT NULL)),
    CONSTRAINT `chk_maintenance_resolution` CHECK (
        (status='pending' AND started_at IS NULL AND resolved_at IS NULL AND resolved_by IS NULL AND resolution_note IS NULL)
        OR (status='in_progress' AND started_at IS NOT NULL AND resolved_at IS NULL AND resolved_by IS NULL AND resolution_note IS NULL)
        OR (status='resolved' AND resolved_at IS NOT NULL AND resolved_by IS NOT NULL
            AND resolution_note IS NOT NULL AND CHAR_LENGTH(TRIM(resolution_note))>0))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `maintenance_events` (
    `event_id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `maintenance_id` INT UNSIGNED NOT NULL,
    `revision` INT UNSIGNED NOT NULL,
    `actor_id` INT UNSIGNED NOT NULL,
    `event_type` ENUM('created','edited','started','resolved') NOT NULL,
    `before_values` JSON DEFAULT NULL,
    `after_values` JSON NOT NULL,
    `created_at` DATETIME(6) NOT NULL COMMENT 'UTC',
    PRIMARY KEY (`event_id`),
    UNIQUE KEY `uq_maintenance_event_revision` (`maintenance_id`,`revision`),
    CONSTRAINT `fk_maintenance_event` FOREIGN KEY (`maintenance_id`) REFERENCES `maintenance_requests` (`maintenance_id`),
    CONSTRAINT `fk_maintenance_event_actor` FOREIGN KEY (`actor_id`) REFERENCES `users` (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
