-- REVIEW ONLY. Separate approval and a verified fresh backup are required.
-- Maintenance window: stop application writes, apply together with updated services.
-- End dates are exclusive: a checkout on 15 Nov permits the next start on 15 Nov.
USE `smart_boarding_db`;

ALTER TABLE `tenancies`
    ADD COLUMN `revision` INT UNSIGNED NOT NULL DEFAULT 0 AFTER `updated_at`,
    DROP CHECK `chk_tenancies_end_date`,
    ADD CONSTRAINT `chk_tenancies_end_date` CHECK (
        (`tenancy_status` = 'open' AND `end_date` IS NULL)
        OR (`end_date` IS NOT NULL AND `end_date` >= `start_date`)
    ),
    -- Open agreements may be adjacent in time; services lock Student and Room
    -- parents and reject overlapping periods before every approval/change.
    DROP INDEX `uq_tenancies_held_student`,
    DROP INDEX `uq_tenancies_held_bed`,
    DROP INDEX `uq_tenancies_held_private_room`,
    ADD INDEX `idx_tenancies_held_student` (`held_student_id`, `start_date`, `end_date`),
    ADD INDEX `idx_tenancies_held_bed` (`held_bed_id`, `start_date`, `end_date`),
    ADD INDEX `idx_tenancies_held_private_room` (`held_private_room_id`, `start_date`, `end_date`);

CREATE TABLE `tenancy_events` (
    `event_id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `tenancy_id` INT UNSIGNED NOT NULL,
    `actor_id` INT UNSIGNED NOT NULL,
    `event_type` ENUM('start_rescheduled', 'move_out_scheduled',
        'move_out_rescheduled', 'move_out_cancelled', 'move_out_confirmed') NOT NULL,
    `old_start_date` DATE NOT NULL,
    `new_start_date` DATE NOT NULL,
    `old_end_date` DATE DEFAULT NULL,
    `new_end_date` DATE DEFAULT NULL,
    `old_status` ENUM('open', 'ended') NOT NULL,
    `new_status` ENUM('open', 'ended') NOT NULL,
    `reason` VARCHAR(500) DEFAULT NULL,
    `revision` INT UNSIGNED NOT NULL,
    `created_at` DATETIME(6) NOT NULL COMMENT 'UTC',
    PRIMARY KEY (`event_id`),
    UNIQUE KEY `uq_tenancy_events_revision` (`tenancy_id`, `revision`),
    KEY `idx_tenancy_events_actor` (`actor_id`),
    CONSTRAINT `fk_tenancy_events_tenancy` FOREIGN KEY (`tenancy_id`)
        REFERENCES `tenancies` (`tenancy_id`),
    CONSTRAINT `fk_tenancy_events_actor` FOREIGN KEY (`actor_id`)
        REFERENCES `users` (`user_id`),
    CONSTRAINT `chk_tenancy_events_dates` CHECK (
        (`old_end_date` IS NULL OR `old_end_date` >= `old_start_date`)
        AND (`new_end_date` IS NULL OR `new_end_date` >= `new_start_date`)
    )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Existing tenancy IDs, source-request UNIQUE, FKs and original agreed rents stay.
-- No DELETE, no automatic bills, no transfer or rent-amendment tables.
