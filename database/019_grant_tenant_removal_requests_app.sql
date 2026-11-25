-- Separate approval required; append-only audit and six decision columns only.
GRANT SELECT, INSERT ON `smart_boarding_db`.`tenant_removal_requests` TO 'smart_boarding_app'@'127.0.0.1';
GRANT UPDATE (`status`,`decided_by`,`decision_note`,`decision_balance`,`decided_at`,`revision`)
    ON `smart_boarding_db`.`tenant_removal_requests` TO 'smart_boarding_app'@'127.0.0.1';
GRANT SELECT, INSERT ON `smart_boarding_db`.`tenant_removal_events` TO 'smart_boarding_app'@'127.0.0.1';
