# Admin Portal 016 — review and explicit approval required

Scope: UC31 Manage User Accounts, UC32 Moderate Boarding Listings, UC33 Review Platform Reports.
No OOAD diagram file was available. The supplied approved use cases are the source for scope.

Full SQL: `016_admin_portal.sql`, `016_grant_admin_portal_app.sql`, `016_admin_portal_test.sql`.
Main changes: two control columns/indexes on users, two on boardings, one append-only audit table.
Existing is_active, role, draft/published state, names, email, hashes, financial and tenancy data stay unchanged.
Default FALSE/0 preserves current behavior for all existing records. No delete/reset or table recreation.

Runtime: existing app already has table-level users/boardings UPDATE. No broader grants are added.
Only SELECT/INSERT on admin_events is new; app cannot update/delete audit history.
These are application role checks in the existing shared runtime account, not separate MySQL Admin credentials.
Isolated schema gets equivalent controls plus DELETE on admin_events solely for disposable fixture cleanup.
No dependency installation is needed. Admin actions never touch bills, prices, payments or bank details.

Suspension leaves users.is_active untouched. Reactivation only removes admin_suspended and cannot override
an independent is_active=FALSE restriction. Existing active-account/public-owner restrictions stay in place.
Admin suspension itself does not silently moderate the listing. Hide/Restore is an explicit separate control.
Public visibility: Owner published + existing active Owner eligibility + NOT admin_hidden. Owner edits cannot
write moderation fields. Restore never changes draft/published. Existing tenancies and agreements are retained.

Before executing: verify a fresh consistent logical snapshot and private-file archive hashes. Restore rehearsal
has not been performed. Apply isolated SQL first, run write/security/integration tests, then fresh main backup,
short controlled main-app restart and main DDL/grant rollout. Compare all original-column row digests after DDL.
MySQL DDL auto-commits: inspect state after any interrupted ALTER and never blindly re-run the migration.
Preflight must find no 016 columns/table. If already/partly applied, stop and inspect metadata.

Rollback: keep additive columns and audit history. Disable Admin routes/writes while investigating; do not
turn off enforcement after any moderation/suspension decisions, since that would expose hidden listings or
re-enable suspended users. Keep the guarded code deployed. Restore only via a separately approved recovery
plan; never DROP new columns/tables as an automatic rollback. A backup is not a tested restore.

No production Admin currently exists. Provisioning is a separate privileged action, requiring separate approval.
The prepared local CLI uses normal hash policy, getpass password entry, existing email OTP verification and
atomic account/audit creation. It never promotes a Student/Owner and has no default credentials. Do not run
provisioning or send an OTP until a specific authorized recipient/account creation has been approved.
The legacy auth challenge ENUM is unchanged: NULL marks a CLI-only registration challenge that public web
verification refuses to consume. The Admin role is assigned only by the approved local verification call.

Status: APPROVED and APPLIED to isolated/main databases on 14 November 2026.
Fresh main backup: `instance/backups/before_admin_portal_20261113T193249Z_21095f.sql` (UTC filename).
Backup hash verified; no restore rehearsal. All 31 original-table column/value digests remained unchanged.
Audit grants verified. `ADMIN_PORTAL_ENABLED=1` activated after successful isolated tests.
First Admin provisioning separately approved; completion is recorded in the private setup result report.
