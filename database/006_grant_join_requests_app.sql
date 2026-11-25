-- REVIEW ONLY: execute only after separate privilege approval and table checks.
-- Owner decisions and future Student pending cancellation update join_requests.
GRANT SELECT, INSERT, UPDATE
ON `smart_boarding_db`.`join_requests`
TO 'smart_boarding_app'@'127.0.0.1';

-- Approval creates a tenancy. Ending/updating it belongs to a future increment
-- and will require a separate privilege review; production history has no DELETE.
GRANT SELECT, INSERT
ON `smart_boarding_db`.`tenancies`
TO 'smart_boarding_app'@'127.0.0.1';
