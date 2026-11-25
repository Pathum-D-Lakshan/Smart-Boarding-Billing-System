# End Stay with an issued-bill review

Superseded by the user's corrected Owner → Admin request requirement. Current behavior and entry
points: [tenant-removal-requests.md](tenant-removal-requests.md). The public direct Owner `end_stay`
action described in this earlier checkpoint is disabled; only the new Admin approval ends a requested
removal. Existing ordinary voluntary checkout/date-management remains separate.

The Owner can end an active tenant's stay today without deleting an account, approval, contract or
financial history. This extends the existing Tenants / Move-Out workflow and existing tables/grants;
there is no schema migration or dependency installation.

Entry points: Tenants → End Stay / Remove Tenant, or an approved Join Request's details → Review Balance
& End Stay. Both lead to the existing centered Tenant dialog. Scheduled tenancies retain their existing
date-management actions. Completed agreements remain read-only, with their balance/history available.

## Balance scope and accuracy

`tenant_settlement.load_settlement` uses the current cursor and filters Owner + Boarding + Student.
It includes all current issued bills at that boarding, including earlier stays. Void bills and other
boardings are excluded. Totals use Decimal. Verified payments count as settled only with a matching
receipt and exact bill amount, consistent with the existing full-payment model. Submitted bank slips
remain Pending Verification and still payable. Invalid verified/receipt records need review.

The UI distinguishes Outstanding Balance, Paid in Full — Issued Bills, No Payment Due — Issued Bills,
Verification Needs Review and No Bills Issued. No Bills Issued never claims that the tenant paid.
Latest 12 invoice rows are displayed; totals and the review fingerprint include every issued bill.
Unissued/final charges are explicitly excluded. End Stay does not calculate a final bill, refund,
proration or debt waiver. Future-issued charges, if any, also stay unchanged and visible.

## Confirmation and transaction

User-approved policy: an outstanding amount does not block ending the stay, but requires explicit
Owner financial acknowledgement and the current application password; unpaid bills remain payable.
Password eye, CSRF, role/ownership, existing password attempt limits and revision checks are reused.
No submitted amount/Student ID/Boarding ID is trusted. End Stay only accepts today's checkout for an
active agreement. The Student account and historical Approved Join Request are not deactivated/rejected.

The backend locks Student → Boarding → Room → Tenancy → Owner, matching existing financial/approval
writers. It re-reads the complete issued-bill/payment/receipt projection under these locks and compares
the reviewed fingerprint. Changed bills, submissions or verification cause a conflict and require fresh
review/acknowledgement; credentials are cleared. The tenancy end/status update and existing lifecycle
audit event commit together. Errors roll back; concurrent/duplicate operations cannot add two events.

## Frozen billing policy

Existing schedule, reschedule and backdated-confirm actions retain `billing_guard.guard_period_change`.
Only the explicit financially reviewed End Stay action can end today's physical assignment while
keeping previously frozen issued bill/allocation snapshots intact. It neither silently recalculates
those snapshots nor changes agreed rent. Corrections/refunds/final charges remain separate Monthly Bills
operations. Existing billing-cohort guards still apply to later approvals in a frozen billing period.
Ending a stay releases the actual Shared Bed or entire Private Room assignment from checkout today;
all other reservations remain protected.

## Verification

`tests/test_tenant_end_stay_mysql.py` uses only approved isolated fixtures: unpaid/paid/pending balances,
history preservation, Student bill access after move-out, private/shared releases, wrong/blank password,
CSRF, financial acknowledgement, stale review, role/Owner isolation, concurrent payment and no-bill state.
Existing lifecycle/billing/payment/Student/auth regressions and Tenant JS confirmation harnesses are
also run. No real user's stay is ended for testing. Native browser visual QA is reported separately.

Manual main-app check: Ctrl+Shift+R → Owner Join Requests → approved request View → Review Balance & End
Stay (or Tenants → End Stay / Remove Tenant). Review the real amounts and issued-bill links. Continue
only if actually intending to end that stay; tick the financial acknowledgement and enter the Owner's
current password. Confirm End Stay. Check Moved Out history, unchanged debt/bills and available assignment.
