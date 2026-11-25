-- REVIEW ONLY. Execute with the approved 008 lifecycle migration.
-- Restrict updates to lifecycle fields; agreed rents/assignments remain immutable.
GRANT UPDATE (`start_date`, `end_date`, `tenancy_status`, `revision`)
ON `smart_boarding_db`.`tenancies` TO 'smart_boarding_app'@'127.0.0.1';
GRANT SELECT, INSERT ON `smart_boarding_db`.`tenancy_events`
TO 'smart_boarding_app'@'127.0.0.1';
