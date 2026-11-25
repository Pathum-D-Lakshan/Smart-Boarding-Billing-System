# Student Settings 015 — approved and applied, 10 November 2026

Approval: `APPROVE STUDENT SETTINGS 015 SQL + GRANTS + TEST SQL`.
Isolated SQL/security tests completed before a fresh hash-verified main backup and
main rollout. All 30 original tables' original-column record digests were unchanged.
The new phone values were NULL and audit table empty before activation. Main audit
grants verified SELECT/INSERT only. `STUDENT_SETTINGS_ENABLED=1` is active on the
existing app at port 5000. No dependency was installed; no restore rehearsal claimed.
Evidence: `instance/student_settings_isolated_rollout_report.json` and
`instance/student_settings_main_rollout_report.json`. Never rerun CREATE/ALTER
blindly on an already migrated schema.

Inspection: main has 30 tables. users has no phone field. Owner contact_phone lives
in owner_settings; reusing an Owner-only bank/settings row for a Student would mix
roles. users full_name/email/password_hash, auth_sessions and auth_request_limits
already provide the remaining account/security infrastructure.

Complete approved SQL: 015_student_settings.sql, 015_grant_student_settings_app.sql
and 015_student_settings_test.sql. Execution followed the approval above.

Minimal changes: one nullable users.contact_phone column (all existing rows NULL;
no name/email/hash/identity change) and one append-only student_settings_events
audit table. No student_accounts/preferences/theme/profile table. Phone is optional,
normalized to +94 if supplied. Theme retains the existing smartboarding-theme key.

Main already has users SELECT/INSERT/UPDATE and existing auth grants; add only
SELECT/INSERT for the new audit table. Do not grant audit UPDATE/DELETE. Isolated
test account gets DELETE on the new audit table for its own fixtures only. No
privilege revocation or broadening of existing table grants is proposed.

Events store self-actor, monotonic revision, before/after allowed profile fields
or safe password-change/session-revocation/theme metadata. No passwords, hashes,
session tokens, bank fields or reset credentials. Lock the current Student users
row before reading its latest audit revision; unique(student_id,revision) protects
against stale/concurrent updates without another revision column/settings table.

Five-minute Settings entry gate, binding and password attempt limits reuse Owner
helpers with role-scoped keys; fresh verification remains mandatory for every save.
Password change revokes all existing sessions and reset grants, then signs out,
matching Owner Settings. No tenancy/bill/payment/maintenance changes or IDs.

Completed procedure: private logical main backup plus private upload archive,
verified hashes; isolated SQL and security/rollback/concurrency tests first; fresh
verified backup in a short maintenance window before the main ALTER. Verified
all original columns' record digests unchanged, new phone values NULL, audit table
empty and exact new grants before restarting the existing main app. DDL auto-commits.

Rollback: keep additive column/table and stop exposing Student Settings if needed.
Never DROP/reset/delete history or restore production data without separate approval.
Existing Owner phone/bank storage and all financial/auth tables are preserved.
