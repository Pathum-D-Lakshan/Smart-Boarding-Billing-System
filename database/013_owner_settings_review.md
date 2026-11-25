# Owner Settings 013 - approval review

Applied 09 November 2026 (Asia/Colombo) after explicit approval:
`APPROVE OWNER SETTINGS 013 SQL + GRANTS + TEST SQL`. Isolated SQL/tests and the
595-test Python regression passed before the main fresh-backup rollout. Original
27 table record digests unchanged; new tables empty; exact grants verified.
Evidence: ignored `instance/settings_rollout_report.json`. Backup hash verified;
restore not rehearsed. Full SQL: `013_owner_settings.sql`,
`013_grant_owner_settings_app.sql`, `013_owner_settings_test.sql`.

Verified live schema: users has full_name VARCHAR(150), email VARCHAR(254),
password_hash VARCHAR(255), role/activation, but no account phone. No Owner bank
storage exists. Boardings already has a different public contact phone; it will
not be silently changed or used as the personal account phone. Existing app
privileges already allow updating users and revoking auth_sessions. No additional
privileges on those existing tables are proposed.

Two new InnoDB tables only, no ALTER/reset/delete of existing tables/records:
owner_settings (one per Owner, personal phone, Boarding-bound bank instruction,
revision/timestamps) and append-only owner_settings_events. Name stays in users;
email/role/identity remain unchanged. Bank account numbers are strings to preserve
leading zeros. No online banking password, PIN or card data is collected.

Bank editing shows a saved last-four mask and blank optional replacement number.
The full stored account is available only in authorized Student transfer
instructions for that Student's own currently payable issued bill/Boarding.
Owner Settings endpoints always require the Owner's five-minute access grant;
each write independently rechecks current password, active Owner, live session,
revision and Boarding ownership under locks. Audit contains relevant name/phone
changes and masked bank metadata/last-four/keyed fingerprint, never full bank
numbers, credential hashes, passwords or OTPs.

Settings password change reuses existing hash/policy and failure throttle,
atomically revokes all current/Remember Me sessions and retires existing reset
grants. Owner is safely signed out, matching the existing reset policy. The
Settings grant is cleared. Challenge -> Owner -> Session locks follow existing
reset/login order; bank writes use Boarding -> Owner -> Session -> Settings.

Appearance reuses only smartboarding-theme localStorage. Preview/cancel is local;
only a password-confirmed POST permits the Settings page to persist the chosen
theme. Header's existing non-sensitive toggle remains available. There is no
parallel persistent theme system or extra preference table.

Main grants: SELECT/INSERT on two new tables; UPDATE only eight operational
owner_settings columns listed in the grant script. No DELETE, owner_id/created_at
UPDATE or audit mutation privileges. Isolated fixture account receives only the
required SELECT/INSERT/UPDATE/DELETE on these two new tables for scoped cleanup.

Read-only consistent SQL/private-file backup verified; restore not rehearsed.
Approval must precede execution. Apply isolated SQL/tests first. Then identify and
pause only the main workspace Flask writer, take/verify a fresh backup, apply main
SQL/grants, confirm existing 27 table record digests unchanged and exact new grants,
restart main port 5000 and perform read-only smoke checks. DDL auto-commits;
inspect any partial failure rather than blindly rerunning CREATE statements.
Rollback disables Settings/bank-instruction integration while preserving records;
DROP/restore/destructive rollback requires separate approval. No new dependency.
