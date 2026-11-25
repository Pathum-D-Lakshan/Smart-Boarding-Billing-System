-- REVIEW ONLY: requires separate approval, fresh verified backup and maintenance.
-- No existing table/data is changed. Money is DECIMAL; checkout is exclusive.
USE `smart_boarding_db`;

CREATE TABLE `billing_cycles` (
    `cycle_id` INT UNSIGNED NOT NULL AUTO_INCREMENT,
    `boarding_id` INT UNSIGNED NOT NULL,
    `period_start` DATE NOT NULL,
    `cycle_number` INT UNSIGNED NOT NULL DEFAULT 1,
    `replaces_cycle_id` INT UNSIGNED DEFAULT NULL,
    `due_date` DATE NOT NULL,
    `electricity_total` DECIMAL(14,2) DEFAULT NULL,
    `water_total` DECIMAL(14,2) DEFAULT NULL,
    `electricity_unallocated` DECIMAL(14,2) NOT NULL DEFAULT 0,
    `water_unallocated` DECIMAL(14,2) NOT NULL DEFAULT 0,
    `state` ENUM('draft','locked','void') NOT NULL DEFAULT 'draft',
    `version` INT UNSIGNED NOT NULL DEFAULT 0,
    `source_digest` CHAR(64) DEFAULT NULL,
    `locked_at` DATETIME(6) DEFAULT NULL COMMENT 'UTC',
    `created_by` INT UNSIGNED NOT NULL,
    `created_at` DATETIME(6) NOT NULL COMMENT 'UTC',
    `active_period` DATE GENERATED ALWAYS AS (CASE WHEN state<>'void' THEN period_start ELSE NULL END) STORED,
    PRIMARY KEY (`cycle_id`),
    UNIQUE KEY `uq_billing_cycle_active` (`boarding_id`,`active_period`),
    UNIQUE KEY `uq_billing_cycle_number` (`boarding_id`,`period_start`,`cycle_number`),
    UNIQUE KEY `uq_billing_cycle_identity` (`cycle_id`,`boarding_id`,`period_start`),
    KEY `idx_billing_cycle_replacement` (`replaces_cycle_id`),
    CONSTRAINT `fk_billing_cycle_boarding` FOREIGN KEY (`boarding_id`) REFERENCES `boardings` (`boarding_id`),
    CONSTRAINT `fk_billing_cycle_creator` FOREIGN KEY (`created_by`) REFERENCES `users` (`user_id`),
    CONSTRAINT `fk_billing_cycle_replacement` FOREIGN KEY (`replaces_cycle_id`) REFERENCES `billing_cycles` (`cycle_id`),
    CONSTRAINT `chk_billing_cycle_period` CHECK (DAY(period_start)=1 AND due_date>=period_start),
    CONSTRAINT `chk_billing_cycle_utilities` CHECK (
        (electricity_total IS NULL AND water_total IS NULL)
        OR (electricity_total>=0 AND water_total>=0 AND electricity_total IS NOT NULL AND water_total IS NOT NULL)),
    CONSTRAINT `chk_billing_cycle_unallocated` CHECK (electricity_unallocated>=0 AND water_unallocated>=0),
    CONSTRAINT `chk_billing_cycle_lock` CHECK (state='draft' OR
        (source_digest IS NOT NULL AND locked_at IS NOT NULL AND electricity_total IS NOT NULL AND water_total IS NOT NULL))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `billing_adjustments` (
    `adjustment_id` INT UNSIGNED NOT NULL AUTO_INCREMENT,
    `boarding_id` INT UNSIGNED NOT NULL,
    `origin_cycle_id` INT UNSIGNED NOT NULL,
    `kind` ENUM('charge','discount') NOT NULL,
    `name` VARCHAR(100) NOT NULL,
    `category` ENUM('internet','cleaning','parking','gas','other','discount') NOT NULL,
    `value` DECIMAL(14,2) NOT NULL,
    `value_type` ENUM('fixed','percentage') NOT NULL DEFAULT 'fixed',
    `application_method` ENUM('per_tenant','shared_total') NOT NULL DEFAULT 'per_tenant',
    `discount_scope` ENUM('rent','subtotal') NOT NULL DEFAULT 'rent',
    `apply_all` BOOLEAN NOT NULL DEFAULT TRUE,
    `recurrence` ENUM('once','monthly') NOT NULL DEFAULT 'once',
    `effective_from` DATE NOT NULL,
    `effective_to` DATE NOT NULL,
    `description` VARCHAR(500) DEFAULT NULL,
    `enabled` BOOLEAN NOT NULL DEFAULT TRUE,
    `request_key` CHAR(32) NOT NULL,
    `fingerprint` CHAR(64) NOT NULL,
    `active_fingerprint` CHAR(64) GENERATED ALWAYS AS (CASE WHEN enabled=TRUE THEN fingerprint ELSE NULL END) STORED,
    PRIMARY KEY (`adjustment_id`),
    UNIQUE KEY `uq_billing_adjustment_request` (`boarding_id`,`request_key`),
    UNIQUE KEY `uq_billing_adjustment_duplicate` (`boarding_id`,`active_fingerprint`),
    KEY `idx_billing_adjustment_period` (`boarding_id`,`enabled`,`effective_from`,`effective_to`),
    CONSTRAINT `fk_billing_adjustment_cycle` FOREIGN KEY (`origin_cycle_id`) REFERENCES `billing_cycles` (`cycle_id`),
    CONSTRAINT `fk_billing_adjustment_boarding` FOREIGN KEY (`boarding_id`) REFERENCES `boardings` (`boarding_id`),
    CONSTRAINT `chk_billing_adjustment_value` CHECK (value>=0 AND (value_type<>'percentage' OR value<=100)),
    CONSTRAINT `chk_billing_adjustment_kind` CHECK (kind='discount' OR value_type='fixed'),
    CONSTRAINT `chk_billing_adjustment_months` CHECK (DAY(effective_from)=1 AND DAY(effective_to)=1 AND effective_to>=effective_from),
    CONSTRAINT `chk_billing_adjustment_flags` CHECK (apply_all IN (0,1) AND enabled IN (0,1))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `billing_adjustment_targets` (
    `adjustment_id` INT UNSIGNED NOT NULL,
    `tenancy_id` INT UNSIGNED NOT NULL,
    PRIMARY KEY (`adjustment_id`,`tenancy_id`),
    CONSTRAINT `fk_billing_target_rule` FOREIGN KEY (`adjustment_id`) REFERENCES `billing_adjustments` (`adjustment_id`),
    CONSTRAINT `fk_billing_target_tenancy` FOREIGN KEY (`tenancy_id`) REFERENCES `tenancies` (`tenancy_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `billing_allocations` (
    `allocation_id` INT UNSIGNED NOT NULL AUTO_INCREMENT,
    `cycle_id` INT UNSIGNED NOT NULL,
    `tenancy_id` INT UNSIGNED NOT NULL,
    `eligible_from` DATE NOT NULL,
    `eligible_until` DATE NOT NULL,
    `eligible_days` SMALLINT UNSIGNED NOT NULL,
    `calendar_days` SMALLINT UNSIGNED NOT NULL,
    `total_tenant_days` INT UNSIGNED NOT NULL,
    `agreed_rent` DECIMAL(14,2) NOT NULL,
    `rent_amount` DECIMAL(16,2) NOT NULL,
    `electricity_share` DECIMAL(14,2) NOT NULL,
    `water_share` DECIMAL(14,2) NOT NULL,
    `charge_amount` DECIMAL(16,2) NOT NULL,
    `discount_amount` DECIMAL(16,2) NOT NULL,
    `final_total` DECIMAL(16,2) NOT NULL,
    `calculation` JSON NOT NULL,
    PRIMARY KEY (`allocation_id`),
    UNIQUE KEY `uq_billing_allocation_tenancy` (`cycle_id`,`tenancy_id`),
    UNIQUE KEY `uq_billing_allocation_identity` (`allocation_id`,`cycle_id`,`tenancy_id`),
    CONSTRAINT `fk_billing_allocation_cycle` FOREIGN KEY (`cycle_id`) REFERENCES `billing_cycles` (`cycle_id`),
    CONSTRAINT `fk_billing_allocation_tenancy` FOREIGN KEY (`tenancy_id`) REFERENCES `tenancies` (`tenancy_id`),
    CONSTRAINT `chk_billing_allocation_days` CHECK (eligible_days>0 AND eligible_days<=calendar_days AND calendar_days BETWEEN 28 AND 31 AND eligible_until>eligible_from AND total_tenant_days>=eligible_days),
    CONSTRAINT `chk_billing_allocation_amounts` CHECK (agreed_rent>0 AND rent_amount>=0 AND electricity_share>=0 AND water_share>=0 AND charge_amount>=0 AND discount_amount>=0 AND final_total>=0),
    CONSTRAINT `chk_billing_allocation_formula` CHECK (final_total=rent_amount+electricity_share+water_share+charge_amount-discount_amount)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `monthly_bills` (
    `bill_id` INT UNSIGNED NOT NULL AUTO_INCREMENT,
    `bill_reference` VARCHAR(40) NOT NULL,
    `cycle_id` INT UNSIGNED NOT NULL,
    `allocation_id` INT UNSIGNED NOT NULL,
    `boarding_id` INT UNSIGNED NOT NULL,
    `tenancy_id` INT UNSIGNED NOT NULL,
    `student_id` INT UNSIGNED NOT NULL,
    `period_start` DATE NOT NULL,
    `recipient_name` VARCHAR(150) NOT NULL,
    `recipient_email` VARCHAR(254) NOT NULL,
    `boarding_snapshot` JSON NOT NULL,
    `unit_snapshot` JSON NOT NULL,
    `final_total` DECIMAL(16,2) NOT NULL,
    `original_due_date` DATE NOT NULL,
    `due_date` DATE NOT NULL,
    `state` ENUM('issued','void') NOT NULL DEFAULT 'issued',
    `revision` INT UNSIGNED NOT NULL DEFAULT 0,
    `issued_by` INT UNSIGNED NOT NULL,
    `issued_at` DATETIME(6) NOT NULL COMMENT 'UTC',
    `active_tenancy_id` INT UNSIGNED GENERATED ALWAYS AS (CASE WHEN state='issued' THEN tenancy_id ELSE NULL END) STORED,
    PRIMARY KEY (`bill_id`),
    UNIQUE KEY `uq_monthly_bill_reference` (`bill_reference`),
    UNIQUE KEY `uq_monthly_bill_active` (`boarding_id`,`period_start`,`active_tenancy_id`),
    KEY `idx_monthly_bill_history` (`boarding_id`,`period_start`,`state`,`bill_id`),
    KEY `idx_monthly_bill_student` (`student_id`,`period_start`),
    CONSTRAINT `fk_monthly_bill_cycle` FOREIGN KEY (`cycle_id`,`boarding_id`,`period_start`) REFERENCES `billing_cycles` (`cycle_id`,`boarding_id`,`period_start`),
    CONSTRAINT `fk_monthly_bill_allocation` FOREIGN KEY (`allocation_id`,`cycle_id`,`tenancy_id`) REFERENCES `billing_allocations` (`allocation_id`,`cycle_id`,`tenancy_id`),
    CONSTRAINT `fk_monthly_bill_student` FOREIGN KEY (`student_id`) REFERENCES `users` (`user_id`),
    CONSTRAINT `fk_monthly_bill_issuer` FOREIGN KEY (`issued_by`) REFERENCES `users` (`user_id`),
    CONSTRAINT `chk_monthly_bill_total` CHECK (final_total>=0 AND due_date>=period_start AND original_due_date>=period_start)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `bill_line_items` (
    `line_id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `bill_id` INT UNSIGNED NOT NULL,
    `line_number` SMALLINT UNSIGNED NOT NULL,
    `kind` ENUM('rent','electricity','water','charge','discount') NOT NULL,
    `description` VARCHAR(255) NOT NULL,
    `amount` DECIMAL(16,2) NOT NULL,
    `adjustment_id` INT UNSIGNED DEFAULT NULL,
    `details` JSON NOT NULL,
    PRIMARY KEY (`line_id`),
    UNIQUE KEY `uq_bill_line_number` (`bill_id`,`line_number`),
    CONSTRAINT `fk_bill_line_bill` FOREIGN KEY (`bill_id`) REFERENCES `monthly_bills` (`bill_id`),
    CONSTRAINT `fk_bill_line_adjustment` FOREIGN KEY (`adjustment_id`) REFERENCES `billing_adjustments` (`adjustment_id`),
    CONSTRAINT `chk_bill_line_sign` CHECK ((kind='discount' AND amount<=0) OR (kind<>'discount' AND amount>=0))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `billing_audit_events` (
    `event_id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `cycle_id` INT UNSIGNED NOT NULL,
    `bill_id` INT UNSIGNED DEFAULT NULL,
    `actor_id` INT UNSIGNED NOT NULL,
    `event_type` VARCHAR(40) NOT NULL,
    `reason` VARCHAR(500) DEFAULT NULL,
    `details` JSON NOT NULL,
    `created_at` DATETIME(6) NOT NULL COMMENT 'UTC',
    PRIMARY KEY (`event_id`),
    KEY `idx_billing_audit_cycle` (`cycle_id`,`event_id`),
    CONSTRAINT `fk_billing_audit_cycle` FOREIGN KEY (`cycle_id`) REFERENCES `billing_cycles` (`cycle_id`),
    CONSTRAINT `fk_billing_audit_bill` FOREIGN KEY (`bill_id`) REFERENCES `monthly_bills` (`bill_id`),
    CONSTRAINT `fk_billing_audit_actor` FOREIGN KEY (`actor_id`) REFERENCES `users` (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
