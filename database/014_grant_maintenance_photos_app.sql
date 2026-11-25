-- Proposed new-table permissions only; no existing privileges are broadened.
GRANT SELECT, INSERT ON `smart_boarding_db`.`maintenance_photos`
    TO 'smart_boarding_app'@'127.0.0.1';
