USE `smart_boarding_db`;

CREATE TABLE `boardings` (
    `boarding_id` INT UNSIGNED NOT NULL AUTO_INCREMENT,
    `owner_id` INT UNSIGNED NOT NULL,
    `boarding_name` VARCHAR(150) NOT NULL,
    `description` TEXT NOT NULL,
    `address` VARCHAR(255) NOT NULL,
    `city` VARCHAR(100) NOT NULL,
    `district` VARCHAR(100) NOT NULL,
    `contact_phone` VARCHAR(20) NOT NULL,
    `contact_email` VARCHAR(254) DEFAULT NULL,
    `facilities` JSON NOT NULL,
    `house_rules` TEXT,
    `status` ENUM('draft', 'published') NOT NULL DEFAULT 'draft',
    `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    PRIMARY KEY (`boarding_id`),
    UNIQUE KEY `uq_boardings_owner` (`owner_id`),
    CONSTRAINT `fk_boardings_owner`
        FOREIGN KEY (`owner_id`) REFERENCES `users` (`user_id`)
        ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT `chk_boardings_facilities_array`
        CHECK (JSON_TYPE(`facilities`) = 'ARRAY')
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;