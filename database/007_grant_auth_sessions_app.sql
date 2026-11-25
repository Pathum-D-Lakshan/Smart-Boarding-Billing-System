-- REVIEW ONLY: separate approval required. No global or existing-table grants.
GRANT SELECT, INSERT, UPDATE
ON `smart_boarding_db`.`auth_sessions`
TO 'smart_boarding_app'@'127.0.0.1';
