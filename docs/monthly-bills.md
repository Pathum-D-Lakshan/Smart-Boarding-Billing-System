# Owner Monthly Bills

The main Flask app registers `owner_bills` at `/owner/monthly-bills`. Monthly Bills
is a working link in the existing shared Owner sidebar. Generated Bills is a
separate history page at `/owner/monthly-bills/generated`. No Student sidebar,
payment receipt, fake account, production fixture, dependency or new app is added.

## Use

1. Choose the billing month and due date; open the period.
2. Save actual electricity and water totals in Utility Bills. Enter explicit `0`
   for no expense; a blank value is incomplete and blocks issuance.
3. Optionally add charges and a discount. Targets are approved eligible tenancy
   IDs, independent of the checkbox selection used to issue bills.
4. Select agreements, recalculate and inspect each row's calculation. Review the
   selected totals and explicitly confirm Generate Monthly Bills.
5. View the resulting persisted bills in Generated Bills. Search/filter, open a
   centered Bill Details dialog or its ordinary page, and use the print view.

Both themes use the shared typography/palette. Tables become labelled cards on
small screens. Dialogs enhance real server forms; without native dialog support,
the same configuration forms and links remain usable. Cancel/Escape/backdrop
restore focus and scrolling and clear passwords. Password eye buttons never submit.

## Calculations and immutability

- Dates use Sri Lankan calendar dates and the existing `[start, checkout)` rule.
  Actual overlap with the selected calendar month determines eligibility. Past
  ended agreements can still be billed for their billable historical days.
- Rent = original agreed monthly rent × eligible days / calendar days, Decimal
  HALF_UP to cents. Shared rents the assigned Bed; Private rents the entire Room.
  Existing physical beds and current listing/default prices do not change rent.
- Electricity/water = actual boarding total × eligible tenant-days / all eligible
  tenant-days. Selecting fewer bills never reduces this denominator. Integer-cent
  floor plus largest remainder reconciles totals; ties use tenancy ID order.
  With no eligible days expenses are unallocated and no bills can be generated.
- A charge is either the same amount per target tenancy or one shared total split
  by the targets' days. One-time is cycle-specific. Monthly requires an explicit
  end month; it can be stopped for subsequent unissued months. No automatic fines.
- One discount per eligible agreement: fixed or percentage, rent-only by default,
  or explicit subtotal. Percentages use prorated rent/subtotal. A fixed amount is
  the entered monetary adjustment, capped by validation against that base (an
  excessive amount is rejected). Discounts never silently reduce utility lines.
- All money is Decimal; submitted calculated totals/status/owner IDs are ignored.
  Preview tokens bind cycle version, selected IDs, due date and source digest and
  expire after 15 minutes. The server recalculates inside the issuance transaction.
- First issuance freezes allocations for ALL eligible agreements, including those
  not selected. Later partial issuance consumes those exact original shares.
  The cycle, allocations, selected bills, lines and audit commit atomically.
  Unique constraints and row locks prevent duplicate/concurrent issuance.

## Corrections and integration

Issued bill amounts and snapshots are immutable. A due-date correction requires
current Owner password, existing failed-password throttle, reason and revision;
original due date is retained. Correct Cycle requires the same security and voids
all issued bills in that cycle, preserving them, then opens a replacement Draft
with utilities and one-time settings copied for review and reissue. Explicit
confirmation is required again. No financial records are hard-deleted.

Join Request approval and Tenants lifecycle writers serialize on the same Student
and Boarding parents. They reject changes to days/cohort in a frozen cycle; changes
outside that financial month remain possible. Correct the cycle first when needed.
Original tenancy agreed rates, source requests and historical bills remain intact.

Stable bill, tenancy, Student and Boarding IDs and snapshots support future Student
bill views, Payments and reports. Issued is not Paid. No collections are fabricated.
Future tables with FKs to monthly_bills block corrections until their reversal/
settlement policy is designed. Future expense reports must exclude replaced cycle
versions from current totals while retaining their history.

## Verification boundaries

`test_billing_calculator.py` tests pure calculations. `test_monthly_bills_mysql.py`
uses the guarded approved isolated schema with disposable example.test accounts,
real login sessions, real SQL writes, concurrency and rollback. The financial-link
blocking test mocks only the future integration boundary because Payments does
not exist. JavaScript tests use a behavioral DOM model, not browser screenshots.
No actual SMTP, main bill issuance, physical printing or native mobile dialog
rendering is claimed by those tests. Backup verification does not mean a restore
has been rehearsed. See `database/009_monthly_bills_review.md` for exact SQL/grants.
