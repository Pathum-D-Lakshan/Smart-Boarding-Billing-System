GRANT SELECT, INSERT ON `smart_boarding_db`.`owner_settings` TO 'smart_boarding_app'@'127.0.0.1';
GRANT UPDATE (`contact_phone`,`bank_boarding_id`,`bank_name`,`account_holder`,`account_number`,`bank_branch`,`revision`,`updated_at`)
    ON `smart_boarding_db`.`owner_settings` TO 'smart_boarding_app'@'127.0.0.1';
GRANT SELECT, INSERT ON `smart_boarding_db`.`owner_settings_events` TO 'smart_boarding_app'@'127.0.0.1';
