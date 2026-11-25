-- Existing users SELECT/INSERT/UPDATE and auth grants are already present.
-- Do not broaden existing privileges. New audit table remains append-only for app.
GRANT SELECT, INSERT ON `smart_boarding_db`.`student_settings_events`
    TO 'smart_boarding_app'@'127.0.0.1';
