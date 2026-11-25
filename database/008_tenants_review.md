# Tenants lifecycle migration review

Execution status (8 November 2026): explicitly approved and applied to the main and
existing isolated test databases. Do not re-run the ALTER. The verified fresh backup
and original-record digest checks are recorded in ignored
`instance/tenants_rollout_report.json`; no production test records were inserted.

Apply `008_tenants_lifecycle.sql` and `008_grant_tenants_app.sql` only after separate
explicit approval. Apply the same lifecycle DDL to the existing isolated test schema,
with SELECT/INSERT/DELETE for its fixture audit events. No new accounts/databases.

The live 8.4.7 schema was inspected. One open tenancy exists. No approved request
lacks its tenancy. `users` has name/email only, so no invented phone/university data.
There are no Billing, Payments or Maintenance tables. Their future integration must
reference the stable tenancy ID; a move-out never means a balance was settled.

## Exact changes

* Add `tenancies.revision` for stale-form/duplicate protection.
* Permit an approved future `end_date` while the stored agreement is `open`.
* Replace the three open-hold UNIQUE indexes with nonunique period indexes. Keep
  source-request UNIQUE and all existing foreign keys. Student/Room parent locks
  serialize all tenancy writes; date-overlap checks replace lifetime open holds.
* Add append-only `tenancy_events` with actor, old/new dates/status, reason, revision,
  UTC event time and two foreign keys. The application cannot UPDATE/DELETE events.
* Give the main account column-specific lifecycle UPDATE, plus event SELECT/INSERT.
  It receives no DELETE, no assignment/rent UPDATE, and no schema privileges.

## Date contract

Periods are `[start_date, end_date)`, with NULL meaning no agreed end. A confirmed
checkout date releases availability starting on that date, never before. Effective
Scheduled/Active/Moved Out states derive from local Asia/Colombo dates without a
scheduler. A scheduled end is binding and takes effect when its date arrives; the
screen describes agreement eligibility, not unverified physical move-in/out.
Moving Out Soon is a subset of Active, not an extra occupant count.

Start-date changes are allowed only while the original and proposed starts are both
in the future. Past agreements cannot be rewritten. Move-out cancellation/extension
must reject any already-approved adjacent reservation or Student agreement.
Transfers and rental amendments remain unavailable until their history and Billing
correction models are separately designed. Original amounts/rate IDs never change.

## Backup and rollout

Create a fresh consistent read-only data/schema backup in ignored `instance/backups`,
hash it and verify the file hash before approval/application. Preserve uploaded cover
files too. Restore is not considered tested just because a backup file exists.
Stop all main Flask writers for the approved DDL/grants (DDL auto-commits), compare
row counts/record digests and schema after applying, run isolated MySQL tests, then
restart port 5000 with the matching services. Stop on any DDL error and inspect the
actual partial state; do not blindly rerun the ALTER.

## Rollback

Keep a code checkpoint and the verified backup. Do not drop audit history or restore
the old UNIQUE indexes once adjacent agreements exist: that could fail or lose data.
On failure stop lifecycle writes, keep read-only access, inspect and roll forward
with separately reviewed SQL. Restoring a database or recreating old uniqueness is
a separate destructive operation requiring approval and a maintenance window.
