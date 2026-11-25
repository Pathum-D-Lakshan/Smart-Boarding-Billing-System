-- Additive finance feature. No existing records or tables are changed.
USE `smart_boarding_db`;

CREATE TABLE `expenses` (
    `expense_id` INT UNSIGNED NOT NULL AUTO_INCREMENT,
    `boarding_id` INT UNSIGNED NOT NULL,
    `expense_name` VARCHAR(150) NOT NULL,
    `amount` DECIMAL(14,2) NOT NULL,
    `expense_date` DATE NOT NULL,
    `request_key` CHAR(32) NOT NULL,
    `revision` INT UNSIGNED NOT NULL DEFAULT 0,
    `created_by` INT UNSIGNED NOT NULL,
    `created_at` DATETIME(6) NOT NULL COMMENT 'UTC',
    `updated_at` DATETIME(6) NOT NULL COMMENT 'UTC',
    `archived_by` INT UNSIGNED DEFAULT NULL,
    `archived_at` DATETIME(6) DEFAULT NULL COMMENT 'UTC',
    PRIMARY KEY (`expense_id`),
    UNIQUE KEY `uq_expense_request` (`boarding_id`,`request_key`),
    KEY `idx_expense_month` (`boarding_id`,`archived_at`,`expense_date`,`expense_id`),
    CONSTRAINT `fk_expense_boarding` FOREIGN KEY (`boarding_id`) REFERENCES `boardings` (`boarding_id`),
    CONSTRAINT `fk_expense_creator` FOREIGN KEY (`created_by`) REFERENCES `users` (`user_id`),
    CONSTRAINT `fk_expense_archiver` FOREIGN KEY (`archived_by`) REFERENCES `users` (`user_id`),
    CONSTRAINT `chk_expense_name` CHECK (CHAR_LENGTH(TRIM(expense_name))>0),
    CONSTRAINT `chk_expense_amount` CHECK (amount>0),
    CONSTRAINT `chk_expense_archive` CHECK ((archived_at IS NULL AND archived_by IS NULL)
        OR (archived_at IS NOT NULL AND archived_by IS NOT NULL))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `expense_events` (
    `event_id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `expense_id` INT UNSIGNED NOT NULL,
    `revision` INT UNSIGNED NOT NULL,
    `actor_id` INT UNSIGNED NOT NULL,
    `event_type` ENUM('created','edited','archived') NOT NULL,
    `before_values` JSON DEFAULT NULL,
    `after_values` JSON NOT NULL,
    `created_at` DATETIME(6) NOT NULL COMMENT 'UTC',
    PRIMARY KEY (`event_id`),
    UNIQUE KEY `uq_expense_event_revision` (`expense_id`,`revision`),
    CONSTRAINT `fk_expense_event_expense` FOREIGN KEY (`expense_id`) REFERENCES `expenses` (`expense_id`),
    CONSTRAINT `fk_expense_event_actor` FOREIGN KEY (`actor_id`) REFERENCES `users` (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
