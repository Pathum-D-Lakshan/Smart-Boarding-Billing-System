-- REVIEW ONLY. No DELETE, schema privileges, balance edits or payment privileges.
GRANT SELECT, INSERT ON `smart_boarding_db`.`billing_cycles` TO 'smart_boarding_app'@'127.0.0.1';
GRANT UPDATE (`due_date`,`electricity_total`,`water_total`,`electricity_unallocated`,`water_unallocated`,`state`,`version`,`source_digest`,`locked_at`)
ON `smart_boarding_db`.`billing_cycles` TO 'smart_boarding_app'@'127.0.0.1';
GRANT SELECT, INSERT ON `smart_boarding_db`.`billing_adjustments` TO 'smart_boarding_app'@'127.0.0.1';
GRANT UPDATE (`enabled`,`effective_to`) ON `smart_boarding_db`.`billing_adjustments` TO 'smart_boarding_app'@'127.0.0.1';
GRANT SELECT, INSERT ON `smart_boarding_db`.`billing_adjustment_targets` TO 'smart_boarding_app'@'127.0.0.1';
GRANT SELECT, INSERT ON `smart_boarding_db`.`billing_allocations` TO 'smart_boarding_app'@'127.0.0.1';
GRANT SELECT, INSERT ON `smart_boarding_db`.`monthly_bills` TO 'smart_boarding_app'@'127.0.0.1';
GRANT UPDATE (`due_date`,`state`,`revision`) ON `smart_boarding_db`.`monthly_bills` TO 'smart_boarding_app'@'127.0.0.1';
GRANT SELECT, INSERT ON `smart_boarding_db`.`bill_line_items` TO 'smart_boarding_app'@'127.0.0.1';
GRANT SELECT, INSERT ON `smart_boarding_db`.`billing_audit_events` TO 'smart_boarding_app'@'127.0.0.1';
