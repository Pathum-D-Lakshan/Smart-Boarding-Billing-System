-- Run only after backup and explicit migration approval. MySQL DDL auto-commits.
USE `smart_boarding_db`;

CREATE TABLE `rooms` (
    `room_id` INT UNSIGNED NOT NULL AUTO_INCREMENT,
    `boarding_id` INT UNSIGNED NOT NULL,
    `room_number` VARCHAR(50) NOT NULL,
    `room_type` ENUM('shared', 'private') NOT NULL,
    `capacity` SMALLINT UNSIGNED NOT NULL,
    `default_bed_rent` DECIMAL(10,2) DEFAULT NULL,
    `floor` VARCHAR(50) DEFAULT NULL,
    `description` TEXT,
    `operational_status` ENUM('ready', 'maintenance')
        NOT NULL DEFAULT 'ready',
    `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,

    PRIMARY KEY (`room_id`),
    UNIQUE KEY `uq_rooms_boarding_number` (`boarding_id`, `room_number`),
    KEY `idx_rooms_boarding_type` (`boarding_id`, `room_type`),

    CONSTRAINT `fk_rooms_boarding`
        FOREIGN KEY (`boarding_id`)
        REFERENCES `boardings` (`boarding_id`)
        ON DELETE RESTRICT ON UPDATE RESTRICT,

    CONSTRAINT `chk_rooms_number`
        CHECK (CHAR_LENGTH(TRIM(`room_number`)) > 0),
    CONSTRAINT `chk_rooms_capacity`
        CHECK (`capacity` > 0),
    CONSTRAINT `chk_rooms_default_rent`
        CHECK (
            (`room_type` = 'shared'
                AND `default_bed_rent` IS NOT NULL
                AND `default_bed_rent` > 0)
            OR
            (`room_type` = 'private'
                AND `default_bed_rent` IS NULL)
        ),
    CONSTRAINT `chk_rooms_operational_status`
        CHECK (`operational_status` IN ('ready', 'maintenance'))
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;


CREATE TABLE `beds` (
    `bed_id` INT UNSIGNED NOT NULL AUTO_INCREMENT,
    `room_id` INT UNSIGNED NOT NULL,
    `bed_label` VARCHAR(50) NOT NULL,
    `operational_status` ENUM('ready', 'maintenance')
        NOT NULL DEFAULT 'ready',
    `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,

    PRIMARY KEY (`bed_id`),
    UNIQUE KEY `uq_beds_room_label` (`room_id`, `bed_label`),

    CONSTRAINT `fk_beds_room`
        FOREIGN KEY (`room_id`)
        REFERENCES `rooms` (`room_id`)
        ON DELETE RESTRICT ON UPDATE RESTRICT,

    CONSTRAINT `chk_beds_label`
        CHECK (CHAR_LENGTH(TRIM(`bed_label`)) > 0),
    CONSTRAINT `chk_beds_operational_status`
        CHECK (`operational_status` IN ('ready', 'maintenance'))
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;


CREATE TABLE `room_rent_rates` (
    `room_rate_id` INT UNSIGNED NOT NULL AUTO_INCREMENT,
    `room_id` INT UNSIGNED NOT NULL,
    `monthly_rent` DECIMAL(10,2) NOT NULL,
    `effective_from` DATETIME(6) NOT NULL COMMENT 'UTC',
    `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (`room_rate_id`),
    UNIQUE KEY `uq_room_rates_effective` (`room_id`, `effective_from`),

    CONSTRAINT `fk_room_rates_room`
        FOREIGN KEY (`room_id`)
        REFERENCES `rooms` (`room_id`)
        ON DELETE RESTRICT ON UPDATE RESTRICT,

    CONSTRAINT `chk_room_rates_positive`
        CHECK (`monthly_rent` > 0)
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;


CREATE TABLE `bed_rent_rates` (
    `bed_rate_id` INT UNSIGNED NOT NULL AUTO_INCREMENT,
    `bed_id` INT UNSIGNED NOT NULL,
    `monthly_rent` DECIMAL(10,2) NOT NULL,
    `effective_from` DATETIME(6) NOT NULL COMMENT 'UTC',
    `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (`bed_rate_id`),
    UNIQUE KEY `uq_bed_rates_effective` (`bed_id`, `effective_from`),

    CONSTRAINT `fk_bed_rates_bed`
        FOREIGN KEY (`bed_id`)
        REFERENCES `beds` (`bed_id`)
        ON DELETE RESTRICT ON UPDATE RESTRICT,

    CONSTRAINT `chk_bed_rates_positive`
        CHECK (`monthly_rent` > 0)
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
