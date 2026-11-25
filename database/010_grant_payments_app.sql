-- Table-specific privileges only; no DELETE, schema or financial amount UPDATE.
GRANT SELECT, INSERT ON `smart_boarding_db`.`payments` TO 'smart_boarding_app'@'127.0.0.1';
GRANT UPDATE (`status`,`decided_by`,`decided_at`,`rejection_reason`,`revision`)
    ON `smart_boarding_db`.`payments` TO 'smart_boarding_app'@'127.0.0.1';
GRANT SELECT, INSERT ON `smart_boarding_db`.`payment_evidence` TO 'smart_boarding_app'@'127.0.0.1';
GRANT SELECT, INSERT ON `smart_boarding_db`.`receipts` TO 'smart_boarding_app'@'127.0.0.1';
GRANT SELECT, INSERT ON `smart_boarding_db`.`payment_events` TO 'smart_boarding_app'@'127.0.0.1';
