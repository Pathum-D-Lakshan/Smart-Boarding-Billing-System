# Shared expense opt-in (021)

Full DDL: `021_shared_expense_opt_in.sql`; main grant:
`021_grant_shared_expense_opt_in_app.sql`. Test SQL contains the same DDL with only
the database changed to the existing isolated test database. Its existing table
UPDATE/INSERT/fixture-cleanup privileges already cover the new column.

* Adds one BOOLEAN `expenses.charge_to_tenants`, default FALSE. No new table.
  No existing amounts, dates, names, opt-ins or invoices are backfilled/changed.
  Every legacy Other expense remains Owner-only. No reset/delete operation.
* Replaces the period CHECK to require Billing/Allocation Month for explicitly
  shared Other expenses. Owner-only Other expenses keep a NULL allocation month.
  Electricity/Water retain their existing default sharing policy; the new flag
  applies only to Other expenses and remains FALSE on utility rows.
* Main privilege change is UPDATE on this one new column only. Existing table
  INSERT/SELECT and other column grants remain. No new DELETE/audit mutation grants.
* Exact allocations reuse the existing tenant-day cent-reconciliation calculator
  across all eligible tenancies. New source snapshots identify each opted-in
  expense exactly once. Matching legacy additional-charge names require review
  before automatic sharing; no legacy configuration is silently deleted.
* Existing locked snapshots retain their original allocation policy/digest. New
  drafts opt into versioned shared sources after activation. A locked period's
  linked source expenses require the existing audited correction flow first.
* Per-Student charge overrides/waivers use existing immutable bill-line details
  JSON and billing audit events, recording original/final amount and reason.
  They do not alter expense totals or redistribute differences to other Students.
  No override table, migration or privilege is needed for that metadata.

## Rollout

Take fresh SQL/private-file backup and verify hashes. Restore rehearsal is not
claimed. Apply approved test DDL only while isolated fixtures are absent, then
run isolated integration tests with mocked SMTP. After tests pass, briefly stop
the verified main Flask process, take another fresh backup, apply main DDL and
limited grant, and verify every original-column digest. Enable
SHARED_EXPENSE_BILLING_ENABLED=1 only after successful rollout, then reload main.
No migration is run automatically on startup.

MySQL DDL auto-commits. Stop and inspect any partial rollout; do not auto-DROP or
restore over live records. Code rollback disables the feature flag and retains
the additive column and history. Reverse DDL/restore needs separate approval.
No dependency installation or real test email is included in this approval.
