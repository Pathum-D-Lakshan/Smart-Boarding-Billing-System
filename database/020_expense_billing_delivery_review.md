# Expenses and monthly bill delivery (020)

Read the complete SQL in `020_expense_billing_delivery.sql` and
`020_grant_expense_billing_delivery_app.sql`. The test SQL is the same DDL with
only the schema changed to the existing isolated Owner Requests test database,
plus SELECT/INSERT/UPDATE/DELETE on the new delivery table for fixture cleanup.

## Data and policy

* Existing expense names, amounts, dates and audit rows remain unchanged. New
  category defaults to Other; no name-based guesses or automatic charges.
* Actual accounting date remains distinct from utility month. Sum every active
  expense in that utility month/category once. Missing is not zero; an explicitly
  recorded zero utility expense is allowed. Other expenses still require >0.
* Existing cycles default to manual_legacy. Issued snapshots stay immutable.
  Preparing an existing draft explicitly switches it to saved expense sources,
  with an audit event. Legacy draft costs are retained in that event.
* First issuance freezes expense IDs/revisions/amounts/category/period in cycle
  JSON. Changes affecting a locked expense-source month require the existing
  password-confirmed audited Correct Cycle workflow first. Paid/linked bills
  retain the existing restriction on financial corrections.
* Final issuance requires a completed calendar month, actual recorded utilities,
  unchanged preview sources and eligible tenancy days. Preview does not issue.
* One delivery row per invoice is inserted in the issuance transaction. Email is
  sent after commit, separately from financial records. Existing billing audit
  events record attempts/outcomes. SMTP acceptance is not proof of inbox arrival.
* Current database email must match the invoice recipient and have a retired
  successful registration OTP marker. Inspection confirmed the current Student
  has that marker. New registrations already retain the same proof. No account
  is marked verified by assumption; no auth table change/backfill is required.
* Failed definite attempts can be retried after a cooldown without issuing again.
  Interrupted/ambiguous SMTP attempts become Uncertain and are not blindly retried.
* App grants add only the listed column updates and new table SELECT/INSERT.
  No DELETE for the main account, no new dependencies, no payment privileges.

## Rollout and backup

1. Take and verify fresh SQL snapshot and file archive hashes; record row counts
   and original-column digests. Do not claim a restore rehearsal.
2. Apply approved test SQL only to the existing isolated schema while fixtures
   are absent. Run isolated integration tests with mocked SMTP.
3. Briefly stop the verified main Flask process, take another fresh backup,
   apply main DDL then grants. Compare every original column/record digest.
4. Enable BILLING_REDESIGN_ENABLED=1 only after checks, then restart main port5000.
   Without activation, existing UI/services remain compatible with old schema.

DDL auto-commits; a partial failure must stop rollout and be inspected. No
automatic DROP, rollback deletion or restore over live records is authorized.
Rollback code activation first if needed; preserve additive columns/table and
all records. Restore/reverse DDL requires separate approval and a reviewed backup.
Real Gmail test messages require a separately approved test recipient; none are
sent by migrations, automated tests, or main read-only smoke checks.
