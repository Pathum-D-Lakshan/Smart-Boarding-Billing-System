-- Additive Owner-only settings. Existing authentication/financial tables are unchanged.
USE `smart_boarding_db`;

CREATE TABLE `owner_settings` (
    `owner_id` INT UNSIGNED NOT NULL,
    `contact_phone` VARCHAR(20) DEFAULT NULL,
    `bank_boarding_id` INT UNSIGNED DEFAULT NULL,
    `bank_name` VARCHAR(100) DEFAULT NULL,
    `account_holder` VARCHAR(150) DEFAULT NULL,
    `account_number` VARCHAR(34) DEFAULT NULL,
    `bank_branch` VARCHAR(100) DEFAULT NULL,
    `revision` INT UNSIGNED NOT NULL DEFAULT 0,
    `created_at` DATETIME(6) NOT NULL COMMENT 'UTC',
    `updated_at` DATETIME(6) NOT NULL COMMENT 'UTC',
    PRIMARY KEY (`owner_id`),
    UNIQUE KEY `uq_settings_bank_boarding` (`bank_boarding_id`),
    CONSTRAINT `fk_settings_owner` FOREIGN KEY (`owner_id`) REFERENCES `users` (`user_id`),
    CONSTRAINT `fk_settings_bank_boarding` FOREIGN KEY (`bank_boarding_id`) REFERENCES `boardings` (`boarding_id`),
    CONSTRAINT `chk_settings_phone` CHECK (contact_phone IS NULL OR contact_phone REGEXP '^[+]94[1-9][0-9]{8}$'),
    CONSTRAINT `chk_settings_bank` CHECK (
        (bank_boarding_id IS NULL AND bank_name IS NULL AND account_holder IS NULL AND account_number IS NULL AND bank_branch IS NULL)
        OR (bank_boarding_id IS NOT NULL AND bank_name IS NOT NULL AND CHAR_LENGTH(TRIM(bank_name))>0
            AND account_holder IS NOT NULL AND CHAR_LENGTH(TRIM(account_holder))>0
            AND account_number IS NOT NULL AND account_number REGEXP '^[0-9]{6,34}$'
            AND bank_branch IS NOT NULL AND CHAR_LENGTH(TRIM(bank_branch))>0))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `owner_settings_events` (
    `event_id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `owner_id` INT UNSIGNED NOT NULL,
    `actor_id` INT UNSIGNED NOT NULL,
    `revision` INT UNSIGNED NOT NULL,
    `event_type` ENUM('account_updated','bank_updated','password_changed','appearance_saved') NOT NULL,
    `before_values` JSON DEFAULT NULL,
    `after_values` JSON NOT NULL,
    `created_at` DATETIME(6) NOT NULL COMMENT 'UTC',
    PRIMARY KEY (`event_id`),
    UNIQUE KEY `uq_settings_event_revision` (`owner_id`,`revision`),
    CONSTRAINT `fk_settings_event_owner` FOREIGN KEY (`owner_id`) REFERENCES `users` (`user_id`),
    CONSTRAINT `fk_settings_event_actor` FOREIGN KEY (`actor_id`) REFERENCES `users` (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
