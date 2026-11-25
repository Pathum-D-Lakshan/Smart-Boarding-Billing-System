GRANT SELECT, INSERT ON `smart_boarding_db`.`expenses` TO 'smart_boarding_app'@'127.0.0.1';
GRANT UPDATE (`expense_name`,`amount`,`expense_date`,`revision`,`updated_at`,`archived_at`,`archived_by`)
    ON `smart_boarding_db`.`expenses` TO 'smart_boarding_app'@'127.0.0.1';
GRANT SELECT, INSERT ON `smart_boarding_db`.`expense_events` TO 'smart_boarding_app'@'127.0.0.1';
