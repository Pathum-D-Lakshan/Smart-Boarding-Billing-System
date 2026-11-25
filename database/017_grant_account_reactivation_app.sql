GRANT SELECT, INSERT, UPDATE (`status`,`decided_by`,`decision_note`,`decided_at`,`acknowledged_at`,`revision`)
ON `smart_boarding_db`.`reactivation_requests` TO 'smart_boarding_app'@'127.0.0.1';
GRANT SELECT, INSERT ON `smart_boarding_db`.`reactivation_events` TO 'smart_boarding_app'@'127.0.0.1';
-- Existing auth_sessions/admin_events grants already cover their additive columns.
