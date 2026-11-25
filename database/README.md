# Database setup

Import `fresh-schema.sql` into a fresh MySQL 8.4 installation. It creates the empty application schema with its indexes, checks and foreign keys. Use this consolidated file for a fresh install. `SmartBoardingSystem.sql` and the numbered migrations document earlier upgrades.

As the database setup account, create the local runtime user with a password you choose. Replace the placeholder before execution. The app should connect as this user.

```sql
CREATE USER 'smart_boarding_app'@'127.0.0.1' IDENTIFIED BY '<local runtime password>';

GRANT SELECT, INSERT ON smart_boarding_db.users TO 'smart_boarding_app'@'127.0.0.1';
GRANT UPDATE (full_name, password_hash, contact_phone, admin_suspended, admin_revision)
    ON smart_boarding_db.users TO 'smart_boarding_app'@'127.0.0.1';
GRANT SELECT, INSERT, UPDATE ON smart_boarding_db.auth_email_challenges TO 'smart_boarding_app'@'127.0.0.1';
GRANT SELECT, INSERT, UPDATE ON smart_boarding_db.auth_request_limits TO 'smart_boarding_app'@'127.0.0.1';
GRANT SELECT, INSERT ON smart_boarding_db.boardings TO 'smart_boarding_app'@'127.0.0.1';
GRANT UPDATE (boarding_name, description, address, city, district, contact_phone, contact_email,
              cover_image_filename, facilities, house_rules, status, updated_at, admin_hidden, admin_revision)
    ON smart_boarding_db.boardings TO 'smart_boarding_app'@'127.0.0.1';
```

Apply the `*_grant_*_app.sql` scripts in numeric order to finish the runtime permissions. The application creates private upload directories as needed. Provision the first Admin with the interactive command in [the Admin portal guide](../docs/admin-portal.md).

## Existing databases

Use the migration that matches the required upgrade after a verified backup and approval. For separate accounting allocation, migration 024 adds the column and its companion script grants permission to update it. [024 upgrade details](024_expense_accounting_period_review.md)

The working application implements pending slip withdrawal using the existing payment and audit tables. Migration 023 is a historical proposal. [Withdrawal design](023_payment_slip_withdrawal_review.md)
