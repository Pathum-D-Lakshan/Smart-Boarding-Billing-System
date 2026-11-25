-- REVIEW ONLY: run after a fresh backup and separate explicit SQL approval.
-- MySQL 8.4 / InnoDB. DDL auto-commits; stop on any error and inspect partial work.
-- Intentionally no IF NOT EXISTS: never silently reuse a different table definition.
USE `smart_boarding_db`;

CREATE TABLE `join_requests` (
    `request_id` INT UNSIGNED NOT NULL AUTO_INCREMENT,
    `student_id` INT UNSIGNED NOT NULL,
    `boarding_id` INT UNSIGNED NOT NULL,
    `preferred_room_id` INT UNSIGNED DEFAULT NULL,
    `preferred_room_type` ENUM('shared', 'private') DEFAULT NULL,
    `intended_start_date` DATE NOT NULL,
    `message` VARCHAR(1000) DEFAULT NULL,
    `status` ENUM('requested', 'approved', 'rejected', 'cancelled')
        NOT NULL DEFAULT 'requested',
    -- Services insert UTC_TIMESTAMP(6); UI displays Asia/Colombo local time.
    `requested_at` DATETIME(6) NOT NULL COMMENT 'UTC',
    `decided_at` DATETIME(6) DEFAULT NULL COMMENT 'UTC',
    -- Owner for approval/rejection; Student for a future pending cancellation.
    `decided_by` INT UNSIGNED DEFAULT NULL,
    `rejection_reason` VARCHAR(500) DEFAULT NULL,
    `created_at` TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `updated_at` TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6),
    -- NULL for historical requests allows multiple resolved records per Student.
    `pending_student_id` INT UNSIGNED GENERATED ALWAYS AS (
        CASE WHEN `status` = 'requested' THEN `student_id` ELSE NULL END
    ) STORED,

    PRIMARY KEY (`request_id`),
    UNIQUE KEY `uq_join_requests_pending_student` (`pending_student_id`),
    KEY `idx_join_requests_boarding_queue`
        (`boarding_id`, `status`, `requested_at`, `request_id`),
    KEY `idx_join_requests_student_history` (`student_id`, `requested_at`, `request_id`),
    KEY `idx_join_requests_preferred_room` (`preferred_room_id`),
    KEY `idx_join_requests_decided_by` (`decided_by`),

    -- Default NO ACTION rejects parent deletion/update; history is not cascaded.
    CONSTRAINT `fk_join_requests_student`
        FOREIGN KEY (`student_id`) REFERENCES `users` (`user_id`),
    CONSTRAINT `fk_join_requests_boarding`
        FOREIGN KEY (`boarding_id`) REFERENCES `boardings` (`boarding_id`),
    CONSTRAINT `fk_join_requests_preferred_room`
        FOREIGN KEY (`preferred_room_id`) REFERENCES `rooms` (`room_id`),
    CONSTRAINT `fk_join_requests_decided_by`
        FOREIGN KEY (`decided_by`) REFERENCES `users` (`user_id`),

    CONSTRAINT `chk_join_requests_status`
        CHECK (`status` IN ('requested', 'approved', 'rejected', 'cancelled')),
    CONSTRAINT `chk_join_requests_room_type`
        CHECK (`preferred_room_type` IS NULL OR `preferred_room_type` IN ('shared', 'private')),
    CONSTRAINT `chk_join_requests_room_preference`
        CHECK (`preferred_room_id` IS NULL OR `preferred_room_type` IS NOT NULL),
    CONSTRAINT `chk_join_requests_intended_date`
        CHECK (`intended_start_date` >= '1000-01-01'),
    CONSTRAINT `chk_join_requests_decision`
        CHECK (
            (`status` = 'requested' AND `decided_at` IS NULL AND `decided_by` IS NULL)
            OR
            (`status` IN ('approved', 'rejected', 'cancelled')
                AND `decided_at` IS NOT NULL AND `decided_by` IS NOT NULL
                AND `decided_at` >= `requested_at`)
        ),
    CONSTRAINT `chk_join_requests_rejection_reason`
        CHECK (
            `rejection_reason` IS NULL
            OR (`status` = 'rejected' AND CHAR_LENGTH(TRIM(`rejection_reason`)) > 0)
        )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;


CREATE TABLE `tenancies` (
    `tenancy_id` INT UNSIGNED NOT NULL AUTO_INCREMENT,
    `source_request_id` INT UNSIGNED NOT NULL,
    `student_id` INT UNSIGNED NOT NULL,
    `boarding_id` INT UNSIGNED NOT NULL,
    `room_id` INT UNSIGNED NOT NULL,
    `bed_id` INT UNSIGNED DEFAULT NULL,
    `start_date` DATE NOT NULL,
    `end_date` DATE DEFAULT NULL,
    -- Open includes scheduled and active agreements; dates determine the UI phase.
    `tenancy_status` ENUM('open', 'ended') NOT NULL DEFAULT 'open',
    `rent_unit` ENUM('bed', 'room') NOT NULL,
    `agreed_monthly_rent` DECIMAL(10,2) NOT NULL,
    -- Snapshot plus immutable source preserves the price agreed at approval.
    `bed_rate_id` INT UNSIGNED DEFAULT NULL,
    `room_rate_id` INT UNSIGNED DEFAULT NULL,
    `created_at` TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `updated_at` TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6),
    `held_student_id` INT UNSIGNED GENERATED ALWAYS AS (
        CASE WHEN `tenancy_status` = 'open' THEN `student_id` ELSE NULL END
    ) STORED,
    `held_bed_id` INT UNSIGNED GENERATED ALWAYS AS (
        CASE WHEN `tenancy_status` = 'open' AND `rent_unit` = 'bed'
            THEN `bed_id` ELSE NULL END
    ) STORED,
    `held_private_room_id` INT UNSIGNED GENERATED ALWAYS AS (
        CASE WHEN `tenancy_status` = 'open' AND `rent_unit` = 'room'
            THEN `room_id` ELSE NULL END
    ) STORED,

    PRIMARY KEY (`tenancy_id`),
    UNIQUE KEY `uq_tenancies_source_request` (`source_request_id`),
    UNIQUE KEY `uq_tenancies_held_student` (`held_student_id`),
    UNIQUE KEY `uq_tenancies_held_bed` (`held_bed_id`),
    UNIQUE KEY `uq_tenancies_held_private_room` (`held_private_room_id`),
    KEY `idx_tenancies_student_status` (`student_id`, `tenancy_status`),
    KEY `idx_tenancies_room_status` (`room_id`, `tenancy_status`),
    KEY `idx_tenancies_bed_status` (`bed_id`, `tenancy_status`),
    KEY `idx_tenancies_boarding_status` (`boarding_id`, `tenancy_status`, `start_date`),
    KEY `idx_tenancies_bed_rate` (`bed_rate_id`),
    KEY `idx_tenancies_room_rate` (`room_rate_id`),

    CONSTRAINT `fk_tenancies_source_request`
        FOREIGN KEY (`source_request_id`) REFERENCES `join_requests` (`request_id`),
    CONSTRAINT `fk_tenancies_student`
        FOREIGN KEY (`student_id`) REFERENCES `users` (`user_id`),
    CONSTRAINT `fk_tenancies_boarding`
        FOREIGN KEY (`boarding_id`) REFERENCES `boardings` (`boarding_id`),
    CONSTRAINT `fk_tenancies_room`
        FOREIGN KEY (`room_id`) REFERENCES `rooms` (`room_id`),
    CONSTRAINT `fk_tenancies_bed`
        FOREIGN KEY (`bed_id`) REFERENCES `beds` (`bed_id`),
    CONSTRAINT `fk_tenancies_bed_rate`
        FOREIGN KEY (`bed_rate_id`) REFERENCES `bed_rent_rates` (`bed_rate_id`),
    CONSTRAINT `fk_tenancies_room_rate`
        FOREIGN KEY (`room_rate_id`) REFERENCES `room_rent_rates` (`room_rate_id`),

    CONSTRAINT `chk_tenancies_status`
        CHECK (`tenancy_status` IN ('open', 'ended')),
    CONSTRAINT `chk_tenancies_start_date`
        CHECK (`start_date` >= '1000-01-01'),
    CONSTRAINT `chk_tenancies_end_date`
        CHECK (
            (`tenancy_status` = 'open' AND `end_date` IS NULL)
            OR (`tenancy_status` = 'ended' AND `end_date` IS NOT NULL AND `end_date` >= `start_date`)
        ),
    CONSTRAINT `chk_tenancies_positive_rent`
        CHECK (`agreed_monthly_rent` > 0),
    CONSTRAINT `chk_tenancies_rental_unit`
        CHECK (
            (`rent_unit` = 'bed' AND `bed_id` IS NOT NULL
                AND `bed_rate_id` IS NOT NULL AND `room_rate_id` IS NULL)
            OR
            (`rent_unit` = 'room' AND `bed_id` IS NULL
                AND `room_rate_id` IS NOT NULL AND `bed_rate_id` IS NULL)
        )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Cross-table role, ownership, preference, source-request identity, room/bed/rate
-- membership and FCFS checks belong in the locked service transaction.
-- Approval, tenancy INSERT and request decision must commit together.
-- Lock the parent Room and check ALL open holds: separate bed/private UNIQUE
-- guards alone do not prevent a mixed-type assignment to the same Room.
-- Approval/cancellation/submission share the Student -> Boarding -> Request ->
-- Room -> Bed lock order. No request submission creates a unit reservation.
