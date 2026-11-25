# Simple Income & Expenses

Owner page: `/owner/income-expenses` in the existing main Flask app. This is a
monthly operational summary of verified collections and allocated paid expenses.
The reference layout is retained: month selector, exactly three cards, three-field
Add Expense form on the left and searchable records on the right. Mobile stacks
the columns. Shared sidebar/header/icons, readable typography and both themes remain.

## Authoritative figures

- Income: existing payments with status verified and method bank_transfer or cash,
  joined once to the Owner's issued-bill relationship. Sum payment amounts only;
  do not sum receipts as another collection. Pending, rejected, unpaid bills and
  zero-balance non-cash settlements are excluded. Payment reversal is not supported
  in the current Payments module; future reversals must preserve this source policy.
- Reporting date: payment decided_at (UTC) mapped to the Sri Lankan month, exactly
  matching the Payments verification/decision-date convention. Use an inclusive
  UTC start and exclusive UTC end, including year/month boundaries. The billing
  month or Student-reported transfer date does not move verified income to another
  reporting month. No manual rent-income table or duplicate income writes exist.
- Expenses: Owner-entered amounts actually paid, grouped by the selected Accounting
  Month, excluding archived records. Older expenses still use the month of their
  paid date. The Expense Date cannot be in the future. Electricity/water values in Monthly Bills are Student billing
  inputs, not proof of supplier payment. They are never imported automatically.
  Record an actually paid utility/repair expense once, manually.
- Balance: Decimal verified income minus Decimal active expenses. Negative balances
  remain negative. Search affects records only, not the three selected-month totals.

`finance_service.monthly_summary(owner_id, month)` is reusable by future Reports /
Owner Dashboard. The same internal query powers the page; no competing JS formulas.
Future Maintenance can link to an existing expense_id rather than duplicate a repair
expense. Reports/Maintenance/full Student Dashboard are not built by this increment.
Students cannot access Owner expense pages, records, history or mutation routes.

## Expense workflow

Name (1–150 characters), amount (DECIMAL(14,2), up to two fractional digits), and
actual paid date (2000-01-01 through today) are required. The selected month
controls reporting. Electricity, Water and shared Other expenses also carry a
separate Billing / Allocation Month.

Add saves creator/Boarding/timestamps and a request key. Repeated clicks with the
same key do not add another expense; a key already used with different values
requires refreshing instead of silently changing an earlier record. New legitimate
separate expenses may share the same name/amount/date with different fresh keys.

Edit opens saved values in one centered modal. The active Owner session, CSRF and
current account/ownership checks protect routine edits without another password.
The existing revision check and automatic audit remain. Sensitive bank/Admin/
issued-financial-correction password gates are unchanged. Current Owner account and
record ownership are checked on the server. Original IDs and created_at remain.
Revision checks plus Boarding/record locks prevent lost concurrent updates. A no-op
does not add audit noise. Update Accounting Month to move an expense between
reporting periods. A blank Accounting Month uses the paid date.

Archive requires its own clear confirmation, without another password. The row is marked
archived with actor/time, preserved and removed from active totals. Repeated archive
is idempotent; archived records cannot be edited. There is no ordinary Delete or
Restore action. Creation, edit and archive each append minimal old/new values,
actor/time and revision to expense_events in the same transaction. Audit cannot be
updated/deleted by the app. The Owner can see the latest ten events in Change History.

## Progressive UI and recovery

Add/filter/month/edit/archive updates use authoritative server-rendered fragments
without reloading the full workspace. Normal links and POST/redirect forms remain
when JS or native dialog support is unavailable. Standalone edit pages use the same
server form. Shared Owner controls remain outside replaced workspace content.

Routine forms contain no password/reason field. Validation preserves proposed
expense inputs for correction. Cancel/Escape/backdrop restore focus/scroll.
Critical writes block duplicate clicks and closing while a save is in progress.

Unknown network/commit outcomes never auto-replay POST. Read-only Refresh reloads
saved records/current revision. An unresolved Add retains its original request key
and input values unless the owned committed attempt is found. This avoids duplicates
even if the first commit completes late. A stale edit requires reading current saved
values. Back-forward cache return invalidates late write responses and requires read
recovery if a mutation was unresolved. Passwords are never put in URLs, logs or storage.

## Data/rollout and verification

Two additive 011 tables: expenses and expense_events, using existing users/boardings
FKs. Existing payment/bill/tenancy data is read only. The app gets SELECT/INSERT plus
seven required expense UPDATE columns, no DELETE or audit mutation. No dependency.
Full SQL and rollout/rollback policy: database/011_income_expenses_review.md.

Pure validation tests cover money, actual dates and Sri Lankan month/year boundaries.
Isolated real MySQL tests cover verified Bank/Cash vs pending/rejected/unpaid amounts,
date boundaries, utilities not imported, totals, search/pagination, edit/archive,
ownership, CSRF, passwordless routine edits, protected issued sources, audit,
idempotency, concurrent writes and rollback.
One actual HTTP test uses the same app on an ephemeral loopback port and isolated
accounts; there is no port 5001 demo or production fixture. Fault-injection error logs
are expected and contain only safe errno codes. JS tests use behavioral DOM models,
not native browser rendering or focus-trap proof. Test fixture cleanup is ID-scoped.

No fake expenses, payments or accounts are inserted into main. Verify the live UI
using actual expenses only. Test currency examples in tests/screenshots are never
seed data. Native desktop/mobile theme appearance remains a browser acceptance check.
