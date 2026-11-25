-- OPTIONAL PHOTO PROPOSAL ONLY. Execute only after separate approval and backup.
USE `smart_boarding_db`;
CREATE TABLE `maintenance_photos` (
    `maintenance_id` INT UNSIGNED NOT NULL,
    `stored_filename` VARCHAR(37) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    `sha256` CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    `byte_count` INT UNSIGNED NOT NULL,
    `width` SMALLINT UNSIGNED NOT NULL,
    `height` SMALLINT UNSIGNED NOT NULL,
    `created_at` DATETIME(6) NOT NULL COMMENT 'UTC',
    PRIMARY KEY (`maintenance_id`),
    UNIQUE KEY `uq_maintenance_photo_filename` (`stored_filename`),
    CONSTRAINT `fk_maintenance_photo_request` FOREIGN KEY (`maintenance_id`)
        REFERENCES `maintenance_requests` (`maintenance_id`),
    CONSTRAINT `chk_maintenance_photo_filename` CHECK (`stored_filename` REGEXP '^[a-f0-9]{32}[.]webp$'),
    CONSTRAINT `chk_maintenance_photo_hash` CHECK (`sha256` REGEXP '^[a-f0-9]{64}$'),
    CONSTRAINT `chk_maintenance_photo_size` CHECK (`byte_count` BETWEEN 1 AND 5242880),
    CONSTRAINT `chk_maintenance_photo_dimensions` CHECK (`width` BETWEEN 1 AND 1920 AND `height` BETWEEN 1 AND 1920)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
