# Monthly Invoice Builder: saved expenses and attached PDFs

The existing Owner Monthly Bills page uses one searchable approved-Student
selector. Student/month changes load agreed prorated rent and recorded
Electricity/Water shares automatically, clearing stale items and signed previews.
Rent remains protected; missing actual utilities are Pending, not invented zeros.
Current-month invoices can be issued as soon as saved costs and approved tenancy
facts validate; payment defaults to the billing month's final day. Future-month
invoices remain preview-only until that month starts. Custom Due Date stays
editable. This supersedes the earlier month-end issuance rule at the user's
explicit clarification on 15 November 2026: issue now, pay at month-end.

## Add Other Expenses

Click + Add Other Expenses to refresh the current Student/month preview and open
a centered searchable selector. It lists only this Owner's saved records using
Allocation Month when present, otherwise Expense Date's month. Category, paid
date, recorded total and the selected Student's share come from MySQL.
Electricity/Water already included automatically cannot be selected again.
Archived, foreign, wrong-month and duplicate source IDs are rejected by Flask.

Choose Other expenses individually and Add Selected Expenses. Explicit selection
is an invoice-specific opt-in, including a valid Owner-only Other cost; it never
changes expenses.charge_to_tenants or another Student's draft. Global Other
sharing flags and legacy configured charges are NOT automatically added by the
new Builder. Existing batch compatibility retains its earlier allocation policy.

The same existing exact-cent tenant-day allocator computes each selected share
over ALL eligible tenancy days, including the frozen common allocation after the
first issue. It does not divide by the number of selected Students. Current
tenancy changes that conflict with frozen facts still block issuance.
Each issued selected line keeps source expense ID/revision, recorded amount,
original calculated share, eligibility days and explicit-selection metadata.

## Simple draft editing

Edit opens a centered two-field Description + Amount modal. Remove immediately
waives that draft line; Undo restores its original calculation. No password,
reason or OTP is needed. Optional source/utility changes retain original/final
amount and description plus automatic Owner audit metadata at issue; waiver
differences are never redistributed. Rent cannot be changed.
+ Add Custom Charge is a secondary modal with only Description + positive Amount,
maximum 20 items. It never creates an Owner Expense. No Qty/Unit Price is shown.
Issued line snapshots cannot be edited through these draft controls.

Routine Income & Expenses Edit/Archive also uses the active Owner session,
CSRF, ownership, current revision and automatic audit instead of another password
prompt. Archive still requires confirmation. Expenses referenced by an issued
invoice are protected even when their global sharing flag is No. Utility/shared
costs in locked periods keep the existing stronger source-correction guard.
Admin decisions, bank details, authentication, payments and issued corrections
retain their separate password/security controls.

## Signed issue and financial safety

The signed review binds normalized selected source snapshots/revisions/shares,
items, overrides, due date, cycle version and common financial digest. The
existing transaction locks Students/Boarding/cycle/Owner and rechecks eligibility,
active accounts, current selected sources, recorded costs and duplicate
constraints before saving invoice, immutable lines, audit and email outbox.
Parent Boarding serialization prevents source edits racing issue.
A failed write rolls back all records. Common allocations/other Student invoices
are unchanged by selecting, editing or removing this Student's draft charges.
Subtotal discounts are recomputed against final chosen charges.

No new migration, grant or dependency is needed. Existing 021 expenses metadata,
bill_line_items.details JSON, billing audit and durable email-delivery rows
provide source tracking and retry state. Old issued amounts/quantity metadata
are read unchanged. Existing unique BILL references and actual server issue
timestamps remain; displays use Asia/Colombo (UTC+05:30).

## Stored-snapshot PDF and delivery

invoice_pdf.py reuses installed ReportLab and existing registered report fonts.
It generates white A4 vector/text PDFs from issued snapshots with unique invoice
reference, Boarding/Student/unit, month, issue date/time, due date, all payable
lines/discounts and exact final total. Voided invoices are clearly marked Do not
pay. Database strings are escaped; long invoices paginate with repeated headers
and page numbers. PDF totals must reconcile with saved lines.

Owner GET /owner/monthly-bills/bills/<id>/pdf and Student GET
/student/bills/<id>/pdf enforce existing role, active-account and owned-record
checks. Both return the same stored snapshot as My Bills with private caching.
No new public file store or upload path is introduced.

Email attaches application/pdf with Invoice-<existing-bill-reference>.pdf to the
verified registered recipient and retains the authenticated portal link.
Rendering/SMTP failure never rolls back or removes an issued bill. It becomes
Failed with safe metadata and the existing controlled retry for the SAME invoice.
PDF rendering is deterministic for an unchanged snapshot, so retries reproduce
the attachment. A separately authorized due-date correction is a new reviewed
snapshot revision, not a silent invoice rewrite.
Accepted/uncertain SMTP outcomes are never blindly resent; acceptance does not
prove Gmail inbox delivery. Real test email still requires recipient approval.
The Owner remains in the Owner portal after sending and sees My Bills availability
plus separate Pending / SMTP Accepted / Failed status, View Invoice and Sent Bills.

Issuing during an open month freezes the current agreed-rent, recorded expense
and eligible tenant-day calculation exactly as reviewed. It does not estimate
missing costs or mark the invoice paid. Later expense/tenancy changes still use
the existing audited correction/conflict rules; issued amounts and other Student
shares are not silently recalculated. Corrections with linked payments retain
their existing restrictions.

## Verification

New guarded isolated MySQL tests cover saved-source selection/month/ownership,
duplicates/utilities, exact sharing, passwordless changes, source preservation,
signed revisions, atomic issue/rollback, protected issued sources, PDF downloads,
Student privacy, PDF MIME/recipient, rendering failure and same-PDF email retry.
Existing payment/receipt/suspension and broader regressions remain applicable.
JavaScript DOM models cover modal selection/search, count, safe text, immediate
Remove, two-field edits and existing late-response/double-send recovery.
PDF tests extract authoritative text, compare deterministic bytes and exercise
multipage/markup/void safeguards. Native Windows PDF renders are inspected.
DOM models and HTTP checks do not prove actual browser responsive layout/focus;
native browser availability and real SMTP/inbox verification are reported apart.
