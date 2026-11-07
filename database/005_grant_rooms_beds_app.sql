-- Apply only after the tables exist and with separate privilege-change approval.
GRANT SELECT, INSERT, UPDATE
ON `smart_boarding_db`.`rooms`
TO 'smart_boarding_app'@'127.0.0.1';

GRANT SELECT, INSERT, UPDATE
ON `smart_boarding_db`.`beds`
TO 'smart_boarding_app'@'127.0.0.1';

-- Rates are append-only for the app; historical prices cannot be updated or deleted.
GRANT SELECT, INSERT
ON `smart_boarding_db`.`room_rent_rates`
TO 'smart_boarding_app'@'127.0.0.1';

GRANT SELECT, INSERT
ON `smart_boarding_db`.`bed_rent_rates`
TO 'smart_boarding_app'@'127.0.0.1';
