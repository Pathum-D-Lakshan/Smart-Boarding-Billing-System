# Maintenance 012 — approval review

Applied 09 November 2026 (Asia/Colombo), following explicit approval:
`APPROVE MAINTENANCE 012 SQL + GRANTS + TEST SQL`. Isolated tests passed before
the fresh-backup/main maintenance rollout. Original 25 table record digests and
exact app grants were verified unchanged/correct; new main tables were empty.
Private backup/rollout evidence: `instance/maintenance_rollout_report.json`.
Backup hash verified; restore not rehearsed. Full SQL: `012_maintenance.sql`, `012_grant_maintenance_app.sql`,
`012_maintenance_test.sql`. Two new InnoDB tables only: maintenance_requests and
append-only maintenance_events. No existing table ALTER/reset/data deletion.
Actual MySQL 8.4.7 schema inspected: 25 tables; current tenancy dates and expenses exist.

Exactly pending -> in_progress -> resolved, with documented immediate pending ->
resolved and required resolution note. No reopen/delete/archive in this simple scope.
Start Work is an authorized CSRF POST with optional visible Owner note. Important
edits and resolution use current password, existing failure throttle, credential
stamp, revision/locks and audit. Repeat resolution is a conflict, not another event.
Non-status corrections and expense linking after resolution are audited/password-
protected; original resolution actor/time/note never change.

Student reports require one current approved open tenancy: start <= local today,
checkout NULL or > today. Recheck under Student -> Boarding -> Room -> Tenancy locks
compatible with lifecycle/approval. Scheduled/ended/unrelated Students cannot create.
Student IDs/Boarding/assigned Room derive from session/current records. Common Area
is allowed. Old own reports remain readable after move-out or a future new tenancy.

Immutable reporter, Boarding and tenancy relationships plus name/location snapshots
preserve history after renames or moves. Student-origin locations remain fixed even
on Owner edits; Owner-created location corrections may use another owned Room/Common
Area and are audited. No occupancy/room operational status or rent mutation occurs.

Optional expense_id references an existing active expense in the same Boarding.
UNIQUE expense_id permits one expense per issue and prevents linking one cost to
multiple current issues. No automatic expense, Student charge, bill, payment or
receipt is created. Later expense archive/edit leaves the link intact with a clear
historical/archived label; Finance remains authoritative. Current expense metadata
and expense/audit identifiers are Owner-only, never in Student detail data.

App privileges: SELECT/INSERT on both tables; UPDATE only the 17 operational fields
listed in the grant script. No reporter/Boarding/tenancy/created_at UPDATE, DELETE,
audit mutation, broad grants or new privileges on other modules. Isolated fixture
account receives SELECT/INSERT/UPDATE/DELETE on only these two new tables.

Rollout: preserve source checkpoint and consistent private SQL/file backup; verify
SHA-256; apply isolated SQL/grants and tests, then fresh backup during verified main
writer maintenance and apply main SQL/grants. Verify original 25 table record digests
and exact grants, then restart the existing app on 5000. DDL auto-commits; inspect
partial failures, do not blindly rerun CREATE. Backup restore is not rehearsed.
Rollback disables Maintenance writes while preserving requests/audit; DROP/restore/
destructive rollback needs separate approval. No production fixtures or new dependency.
