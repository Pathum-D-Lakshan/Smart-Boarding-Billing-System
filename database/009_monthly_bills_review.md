# Monthly Bills migration and calculation review

Applied on 08 November 2026 after the explicit approval
`APPROVE MONTHLY BILLS 009 SQL + GRANTS + TEST SQL`. The isolated 009 DDL/grants and
23 real isolated billing tests passed before main rollout. The main Flask writers
were stopped, a fresh SHA-256-verified backup was retained, and the two main SQL/
grant scripts were applied. All 12 original table record digests were unchanged;
seven empty billing tables and the exact limited grants were verified. No main
bills, test accounts, payments or other financial data were inserted.

Private backup manifest and rollout verification are retained under ignored
`instance/backups/` and `instance/monthly_bills_rollout_report.json`. Backup restore
has not been rehearsed. The scripts remain explicit one-time migrations: do not
blindly rerun CREATE or reset the tables. Further schema/grant changes still need
separate approval.

## Exact schema

`009_monthly_bills.sql` contains the complete DDL for seven new InnoDB tables:
`billing_cycles`, `billing_adjustments`, `billing_adjustment_targets`,
`billing_allocations`, `monthly_bills`, `bill_line_items`, `billing_audit_events`.
It does not ALTER, recreate or reset an existing table. Every relationship uses FKs.
The active period and active tenancy/bill UNIQUE keys are final duplicate guards.

`009_grant_monthly_bills_app.sql` grants SELECT/INSERT to those tables and limited
column UPDATE for draft metadata, rule expiry, controlled bill due-date corrections
and audited cycle void/replacement. Allocations, financial lines and audit events
cannot be updated/deleted by the main app. No DELETE or payment privileges.
`009_monthly_bills_test.sql` applies identical DDL to the already approved isolated
test database and grants fixture-only SELECT/INSERT/UPDATE/DELETE on new tables.

## Financial policy

Dates use the existing `[start, checkout)` convention. Rent is the approved tenancy
amount times eligible days divided by actual calendar days, rounded HALF_UP to two
decimal places. Shared is per assigned Bed; Private is the entire Room. Current
listing prices never replace an agreement. Transfers/rent amendments are not yet
supported by Tenants, so billing uses the preserved original agreed rate.

Electricity, water and shared charges use tenant-days. Cent amounts use floor plus
largest remainder; ties use ascending tenancy ID. This is deterministic and exactly
reconciles each total. All eligible tenancies determine utilities, even if generation
selects only one. Zero inputs are explicitly saved; blank is missing. With no tenant
days the entire expense is reported unallocated and no bill is generated.

On first issue the entire cohort/allocation is frozen, including ungenerated shares.
Later partial issues reuse that snapshot. Source/config changes invalidate previews;
date/approval guards prevent changing a frozen cohort through Tenants/Join Requests.
Boarding parent locks serialize both billing and tenancy writes without reversing
the Student -> Boarding lock order used by existing approvals.

One-time charges belong to their cycle. Monthly recurring charges have explicit
start/end months and apply to all or selected eligible tenancy IDs. Per-tenant and
shared-total application are distinct. Rules have request/fingerprint deduplication.
Only one effective discount per tenancy is allowed: fixed/percentage, rent/subtotal.
Excessive discounts are rejected; totals cannot become negative.

## Corrections and future integration

Issued amounts/lines never change silently. Due-date corrections require current
Owner password, throttle, revision, reason and audit; original due date is retained.
Utility/charge/discount corrections require an explicit password-confirmed cycle
replacement: all issued bills in that cycle become Void, their snapshots remain,
and a replacement Draft is created. Review and issue its replacement bills again.
Any future external financial FK dependency (e.g. Payments) blocks these corrections
until its own settlement/reversal policy is implemented. Issuance is not payment.
Future income/expense reports must exclude superseded cycle versions from current
expense totals while retaining them as history. No fake paid status or receipt.

## Backup, rollout and rollback

Before approval/application take a consistent read-only private schema/data backup,
verify its SHA-256 and cover archive, and retain a manifest. Restore is not considered
tested merely because the backup exists. Test the isolated DDL first. Stop verified
main Flask writers for the approved rollout; DDL auto-commits. Compare original table
record digests and precise grants afterwards, then start the matching main code.
Stop on partial failure and inspect actual schema; do not blindly rerun CREATE.

Rollback should disable billing writes while preserving all issued financial data.
Do not DROP billing tables or delete bills to roll back. Any restore/destructive
rollback requires separate approval. Existing code/worktree checkpoints remain.
