# Account Restriction / Reactivation 017 — approved and applied

Full SQL: `017_account_reactivation.sql`, `017_grant_account_reactivation_app.sql`,
`017_account_reactivation_test.sql`. Adds two small tables, one nullable public-reason field on the existing
Admin audit and restricted scope/event fields on auth_sessions. No duplicate users or authentication system.
Existing session rows default to normal, current audit reasons remain private (new field defaults NULL).
No account, suspension, role, password, email, financial or tenancy record is reset/altered by the migration.

Restricted sessions: 15-minute maximum, never Remember Me, bound to credential stamp + current suspension
event, no normal user_id/session-token identity in their cookie. Every normal token validator checks normal
scope after activation. All business routes deny restricted identities, even after appeal approval, until
a fresh normal Login. Existing registration OTP and normal authentication factors remain unchanged.

Appeals: UNIQUE(user,event) allows one request per suspension, preserving rejected history and preventing
repeat spam. Request state and account suspension are separate. Admin decisions lock actor/user/request,
use existing password limits + CSRF, write decision/audit atomically, and revoke restricted sessions on approval.
Manual Reactivate resolves any pending current-event appeal in the same transaction. New suspension has a
new audit event; previous appeals cannot activate it. Approval never overrides independent is_active=FALSE.
User acknowledgement is explicit POST and persistent per decision, not an automatic read/other-browser event.

Privacy: old admin_events.reason may contain internal information and is NEVER automatically exposed.
Old suspensions without an explicitly user-visible reason show a clear explanation-unavailable message;
date/time still come from the actual current event. New suspension forms label the reason as user-visible.
No backfill, main fake suspension, appeal or decision is performed. UTC storage is converted once to
Asia/Colombo for display, rather than relabelled. No email provider/dependency needed for appeals.

New runtime rights: request SELECT/INSERT and six workflow columns UPDATE; audit SELECT/INSERT only.
No DELETE on main, no broad grants. Dedicated isolated test account additionally gets table-specific
DELETE for fixture cleanup. Existing auth/audit grants are unchanged.

Rollout: fresh consistent backup + private-file archive, verify hashes (restore rehearsal not claimed),
isolated SQL/write tests first, short main maintenance window, fresh backup, main SQL/grants and original
column data digest verification. DDL auto-commits; stop on partial/already-applied migration and inspect.
Activation flag ACCOUNT_REACTIVATION_ENABLED=1 only after verified rollout and tests. Keep enforcement
enabled once restricted sessions exist. Safe rollback keeps additive tables/audits and guards; never drop
data or disable scope enforcement as an automatic rollback. Recovery requires a separately reviewed plan.

Status: APPROVED and APPLIED to isolated/main databases on 14 November 2026.
Main backup: `instance/backups/before_reactivation_20261113T205918Z_7b9e85.sql` (UTC filename).
Hashes verified; restore rehearsal not performed. All 32 original-table column/value digests remained unchanged.
Exact audit/table/column grants verified. ACCOUNT_REACTIVATION_ENABLED=1 activated after isolated testing.
No main suspension, reactivation or appeal test actions were executed. Existing user work is preserved.
