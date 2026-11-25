-- Existing users/boardings grants already cover the new controls. Add only audit access.
GRANT SELECT, INSERT ON `smart_boarding_db`.`admin_events` TO 'smart_boarding_app'@'127.0.0.1';
