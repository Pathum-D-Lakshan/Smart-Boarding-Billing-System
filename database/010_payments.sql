-- Review before execution. Additive only: preserve all issued bills and users.
USE `smart_boarding_db`;

CREATE TABLE `payments` (
    `payment_id` INT UNSIGNED NOT NULL AUTO_INCREMENT,
    `payment_reference` VARCHAR(44) NOT NULL,
    `bill_id` INT UNSIGNED NOT NULL,
    `amount` DECIMAL(16,2) NOT NULL,
    `method` ENUM('bank_transfer','cash','zero_balance') NOT NULL,
    `status` ENUM('submitted','verified','rejected') NOT NULL,
    `payment_date` DATE NOT NULL,
    `bank_name` VARCHAR(100) DEFAULT NULL,
    `transaction_reference` VARCHAR(100) DEFAULT NULL,
    `note` VARCHAR(500) DEFAULT NULL,
    `submitted_by` INT UNSIGNED NOT NULL,
    `submitted_at` DATETIME(6) NOT NULL COMMENT 'UTC',
    `decided_by` INT UNSIGNED DEFAULT NULL,
    `decided_at` DATETIME(6) DEFAULT NULL COMMENT 'UTC',
    `rejection_reason` VARCHAR(500) DEFAULT NULL,
    `revision` INT UNSIGNED NOT NULL DEFAULT 0,
    `request_key` CHAR(32) NOT NULL,
    `active_bill_id` INT UNSIGNED GENERATED ALWAYS AS (
        CASE WHEN status IN ('submitted','verified') THEN bill_id ELSE NULL END) STORED,
    PRIMARY KEY (`payment_id`),
    UNIQUE KEY `uq_payment_reference` (`payment_reference`),
    UNIQUE KEY `uq_payment_active_bill` (`active_bill_id`),
    UNIQUE KEY `uq_payment_request` (`submitted_by`,`request_key`),
    UNIQUE KEY `uq_payment_identity` (`payment_id`,`bill_id`),
    KEY `idx_payment_bill_history` (`bill_id`,`submitted_at`),
    KEY `idx_payment_decision` (`status`,`decided_at`,`submitted_at`),
    CONSTRAINT `fk_payment_bill` FOREIGN KEY (`bill_id`) REFERENCES `monthly_bills` (`bill_id`),
    CONSTRAINT `fk_payment_submitter` FOREIGN KEY (`submitted_by`) REFERENCES `users` (`user_id`),
    CONSTRAINT `fk_payment_decider` FOREIGN KEY (`decided_by`) REFERENCES `users` (`user_id`),
    CONSTRAINT `chk_payment_method` CHECK (
        (method='bank_transfer' AND amount>0 AND transaction_reference IS NOT NULL AND CHAR_LENGTH(TRIM(transaction_reference))>0)
        OR (method='cash' AND amount>0 AND bank_name IS NULL AND transaction_reference IS NULL)
        OR (method='zero_balance' AND amount=0 AND bank_name IS NULL AND transaction_reference IS NULL)),
    CONSTRAINT `chk_payment_decision` CHECK (
        (status='submitted' AND method='bank_transfer' AND decided_by IS NULL AND decided_at IS NULL AND rejection_reason IS NULL)
        OR (status='verified' AND decided_by IS NOT NULL AND decided_at IS NOT NULL AND rejection_reason IS NULL)
        OR (status='rejected' AND method='bank_transfer' AND decided_by IS NOT NULL AND decided_at IS NOT NULL
            AND rejection_reason IS NOT NULL AND CHAR_LENGTH(TRIM(rejection_reason))>0))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `payment_evidence` (
    `evidence_id` INT UNSIGNED NOT NULL AUTO_INCREMENT,
    `payment_id` INT UNSIGNED NOT NULL,
    `stored_filename` VARCHAR(36) NOT NULL,
    `media_type` VARCHAR(30) NOT NULL,
    `byte_count` INT UNSIGNED NOT NULL,
    `sha256` CHAR(64) NOT NULL,
    `created_at` DATETIME(6) NOT NULL COMMENT 'UTC',
    PRIMARY KEY (`evidence_id`),
    UNIQUE KEY `uq_payment_evidence` (`payment_id`),
    UNIQUE KEY `uq_payment_evidence_filename` (`stored_filename`),
    CONSTRAINT `fk_payment_evidence` FOREIGN KEY (`payment_id`) REFERENCES `payments` (`payment_id`),
    CONSTRAINT `chk_payment_evidence_type` CHECK (media_type IN ('image/jpeg','image/png','application/pdf')),
    CONSTRAINT `chk_payment_evidence_size` CHECK (byte_count BETWEEN 1 AND 10485760)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `receipts` (
    `receipt_id` INT UNSIGNED NOT NULL AUTO_INCREMENT,
    `receipt_reference` VARCHAR(44) NOT NULL,
    `payment_id` INT UNSIGNED NOT NULL,
    `bill_id` INT UNSIGNED NOT NULL,
    `snapshot` JSON NOT NULL,
    `snapshot_sha256` CHAR(64) NOT NULL,
    `issued_at` DATETIME(6) NOT NULL COMMENT 'UTC',
    PRIMARY KEY (`receipt_id`),
    UNIQUE KEY `uq_receipt_reference` (`receipt_reference`),
    UNIQUE KEY `uq_receipt_payment` (`payment_id`),
    CONSTRAINT `fk_receipt_payment` FOREIGN KEY (`payment_id`,`bill_id`) REFERENCES `payments` (`payment_id`,`bill_id`),
    CONSTRAINT `fk_receipt_bill` FOREIGN KEY (`bill_id`) REFERENCES `monthly_bills` (`bill_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `payment_events` (
    `event_id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `payment_id` INT UNSIGNED NOT NULL,
    `actor_id` INT UNSIGNED NOT NULL,
    `event_type` ENUM('submitted','verified','rejected','cash_recorded','zero_settled') NOT NULL,
    `details` JSON NOT NULL,
    `created_at` DATETIME(6) NOT NULL COMMENT 'UTC',
    PRIMARY KEY (`event_id`),
    KEY `idx_payment_event_history` (`payment_id`,`event_id`),
    CONSTRAINT `fk_payment_event` FOREIGN KEY (`payment_id`) REFERENCES `payments` (`payment_id`),
    CONSTRAINT `fk_payment_event_actor` FOREIGN KEY (`actor_id`) REFERENCES `users` (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
