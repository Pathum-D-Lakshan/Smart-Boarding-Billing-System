-- Additive Student Settings; execute once only after explicit approval and backup.
USE `smart_boarding_db`;
ALTER TABLE `users`
    ADD COLUMN `contact_phone` VARCHAR(20) NULL DEFAULT NULL,
    ADD CONSTRAINT `chk_users_contact_phone`
        CHECK (contact_phone IS NULL OR contact_phone REGEXP '^[+]94[1-9][0-9]{8}$');

CREATE TABLE `student_settings_events` (
    `event_id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `student_id` INT UNSIGNED NOT NULL,
    `actor_id` INT UNSIGNED NOT NULL,
    `revision` INT UNSIGNED NOT NULL,
    `event_type` ENUM('account_updated','password_changed','appearance_saved') NOT NULL,
    `before_values` JSON DEFAULT NULL,
    `after_values` JSON NOT NULL,
    `created_at` DATETIME(6) NOT NULL COMMENT 'UTC',
    PRIMARY KEY (`event_id`),
    UNIQUE KEY `uq_student_settings_revision` (`student_id`,`revision`),
    CONSTRAINT `fk_student_settings_user` FOREIGN KEY (`student_id`) REFERENCES `users` (`user_id`),
    CONSTRAINT `fk_student_settings_actor` FOREIGN KEY (`actor_id`) REFERENCES `users` (`user_id`),
    CONSTRAINT `chk_student_settings_actor` CHECK (student_id=actor_id AND revision>0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
