-- Review and back up the database before executing this additive migration.
USE `smart_boarding_db`;

ALTER TABLE `boardings`
    ADD COLUMN `cover_image_filename` VARCHAR(100) NULL DEFAULT NULL;
