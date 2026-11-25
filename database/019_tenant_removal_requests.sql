-- Awaiting separate approval. Add request/audit records only; preserve existing agreements/finances.
USE `smart_boarding_db`;
CREATE TABLE `tenant_removal_requests` (
    `request_id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `tenancy_id` INT UNSIGNED NOT NULL,
    `owner_id` INT UNSIGNED NOT NULL,
    `boarding_id` INT UNSIGNED NOT NULL,
    `student_id` INT UNSIGNED NOT NULL,
    `reason` VARCHAR(500) NOT NULL,
    `submitted_balance` JSON NOT NULL,
    `tenancy_revision` INT UNSIGNED NOT NULL,
    `status` ENUM('pending','approved','rejected') NOT NULL DEFAULT 'pending',
    `submitted_at` DATETIME(6) NOT NULL COMMENT 'UTC',
    `decided_by` INT UNSIGNED NULL,
    `decision_note` VARCHAR(400) NULL,
    `decision_balance` JSON NULL,
    `decided_at` DATETIME(6) NULL COMMENT 'UTC',
    `revision` INT UNSIGNED NOT NULL DEFAULT 0,
    `pending_tenancy_id` INT UNSIGNED GENERATED ALWAYS AS (CASE WHEN status='pending' THEN tenancy_id ELSE NULL END) STORED,
    PRIMARY KEY (`request_id`),
    UNIQUE KEY `uq_tenant_removal_pending` (`pending_tenancy_id`),
    KEY `ix_tenant_removal_owner` (`owner_id`,`tenancy_id`,`request_id`),
    KEY `ix_tenant_removal_queue` (`status`,`submitted_at`,`request_id`),
    FOREIGN KEY (`tenancy_id`) REFERENCES `tenancies` (`tenancy_id`),
    FOREIGN KEY (`owner_id`) REFERENCES `users` (`user_id`),
    FOREIGN KEY (`student_id`) REFERENCES `users` (`user_id`),
    FOREIGN KEY (`boarding_id`) REFERENCES `boardings` (`boarding_id`),
    FOREIGN KEY (`decided_by`) REFERENCES `users` (`user_id`),
    CONSTRAINT `chk_tenant_removal_reason` CHECK (CHAR_LENGTH(TRIM(reason)) BETWEEN 1 AND 500),
    CONSTRAINT `chk_tenant_removal_state` CHECK (
        (status='pending' AND decided_by IS NULL AND decided_at IS NULL AND decision_note IS NULL AND decision_balance IS NULL AND revision=0)
        OR (status IN ('approved','rejected') AND decided_by IS NOT NULL AND decided_at IS NOT NULL AND decided_at>=submitted_at AND revision=1
            AND (status<>'rejected' OR CHAR_LENGTH(TRIM(COALESCE(decision_note,'')))>0)
            AND (status<>'approved' OR decision_balance IS NOT NULL)))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE `tenant_removal_events` (
    `event_id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `request_id` BIGINT UNSIGNED NOT NULL,
    `actor_id` INT UNSIGNED NOT NULL,
    `action` ENUM('submitted','approved','rejected') NOT NULL,
    `created_at` DATETIME(6) NOT NULL COMMENT 'UTC',
    PRIMARY KEY (`event_id`),
    UNIQUE KEY `uq_tenant_removal_event` (`request_id`,`action`),
    FOREIGN KEY (`request_id`) REFERENCES `tenant_removal_requests` (`request_id`),
    FOREIGN KEY (`actor_id`) REFERENCES `users` (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
