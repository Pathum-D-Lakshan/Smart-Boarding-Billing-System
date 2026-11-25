-- Separately approved 14 Nov 2026. Preserve every request and decision; allow retries after rejection.
USE `smart_boarding_db`;
ALTER TABLE `reactivation_requests`
    ADD COLUMN `pending_suspension_id` BIGINT UNSIGNED
        GENERATED ALWAYS AS (CASE WHEN `status`='pending' THEN `suspension_event_id` ELSE NULL END) STORED,
    ADD UNIQUE KEY `uq_reactivation_pending` (`user_id`,`pending_suspension_id`),
    ADD KEY `ix_reactivation_history` (`user_id`,`suspension_event_id`,`request_id`),
    DROP INDEX `uq_reactivation_suspension`;
