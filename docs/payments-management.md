# Payments: manual bank verification, cash and receipts

The existing main Flask app registers three blueprints: Owner `/owner/payments`,
minimal Student `/student/bills` + `/student/payments`, and protected documents
`/payments/<payment_id>/slip` + `/payments/receipts/<receipt_id>`. This is not a
payment gateway or an automatic bank/fraud verification service.

## Normal workflow

1. Owner issues a real Monthly Bill. Its immutable final_total is authoritative.
2. Student opens My Bills, completes the transfer independently, then submits the
   exact full amount, actual payment date, reference and private JPG/PNG/PDF slip.
3. Owner opens Payments -> Pending Verification -> centered View Details, checks
   the evidence and their bank records independently, and chooses Verify or Reject.
4. Both decisions need current password, existing failed-password throttle, explicit
   confirmation, scope, CSRF and fresh revision. Rejection requires a reason.
5. Verification, one receipt and the derived bill Paid state commit together.
   Rejection preserves evidence/history, leaves the bill unpaid and permits a new
   attempt with a fresh request key. A duplicate click reuses its original attempt.

Cash: Owner chooses a valid unpaid bill, reviews its authoritative full amount,
enters the actual received date/note, confirms physical receipt and current password.
One verified cash record and receipt commit together, without invented bank fields.
A pending bank submission must first be reviewed/rejected; cash cannot bypass it.

Zero bills: Student does not transfer money or submit a meaningless slip. Owner
explicitly confirms a password-protected zero_balance settlement. It collects 0.00,
has a clearly labelled non-cash settlement receipt and never fabricates a transfer.

## Integrity and concurrency

Four additive 010 tables: payments, payment_evidence, receipts, payment_events.
An active_bill_id generated UNIQUE key covers pending and verified attempts together.
Rejected attempts remain immutable history and release the active slot. Actor/request
keys prevent replay; receipt/payment UNIQUE keys prevent repeated receipt issuance.

Writers use Student -> Boarding -> Cycle -> Owner -> Bill -> Payment row locks,
compatible with Monthly Bills and Tenants. They recheck current active Owner,
credential stamp, issued bill, amount, status, revision and evidence before commit.
Bill corrections and payment operations cannot win against the same bill concurrently.
Faults roll back ledger rows, decision, receipt and event together. No business action
updates bill financial amounts, room assignments, agreed rents or tenancy records.

Paid is a derived read of the one verified payment/receipt, not a second mutable bill
flag. Pending never means paid or collected. A corrupt verification missing a receipt
is labelled Needs Review and cannot be silently recreated by a Verify retry. No
reversal, refund, delete or editing of verified amounts is included.

Existing Monthly Bills financial-link guards now detect real payment/receipt FKs.
They block due-date corrections or cycle replacement after any linked payment
history, including rejected attempts. A future financial reversal policy needs its
own design/approval before relaxing this protection. Frozen-month tenancy guards
also remain; a checkout affecting issued days needs the existing billing correction
policy. Move-out never removes Student ownership of historical bills/documents.

## Private evidence

- Default 5 MiB; `PAYMENT_MAX_UPLOAD_BYTES` is configurable and capped at 10 MiB.
  `PAYMENT_UPLOAD_ROOT` can override the private default `receipts/slips` for tests.
- Extension, actual signature/content, decoded image integrity, dimensions/pixels,
  complete endings and animation checks. MIME provided by the browser is untrusted.
- pypdf 7.0.0 validates static PDFs in a separate six-second worker with bounded
  page tree/object/array/stream/decompression settings. Up to 10 pages; encrypted
  PDFs, forms, attachments, scripts/actions and active links are rejected. Use a
  static PDF or image alternative. No external PDF decoder is launched.
- Original accepted bytes are preserved and SHA-256 recorded; generated server-side
  UUID filenames never contain Student/bank identifiers. Storage is outside static.
- Every image view, PDF download and receipt checks the current session plus actual
  Student bill ownership or Boarding Owner ownership. Evidence hash/size is checked.
  Responses use no-store, nosniff, same-origin, no-referrer and sandbox headers.
  PDF is attachment-only; no active PDF iframe/object is embedded in the app.
- Failed inserts clean up only files whose absence from evidence metadata can be
  confirmed using a fresh DB read. An uncertain commit/DB outage retains the file
  for controlled review instead of deleting possibly committed evidence.
- No antivirus is available. Content validation is not a malware-free guarantee.

## Receipts and reporting

Receipt numbers/IDs are stable and unique; immutable JSON+hash snapshots preserve
the bill, recipient, boarding/unit, method, amount, dates and verifying Owner name.
Receipt views are Owner/Student protected even after move-out. Print / Save as PDF
uses print-friendly HTML and the browser's print dialog, not a new PDF renderer.
There are no fabricated digital signatures or bank approval stamps.

Owner reporting defaults to the current Sri Lankan month. Date range and method
determine summary cards; tabs/search additionally filter table rows. The reporting
date is the decision date for reviewed records and submission date while pending.
Total Collected sums only verified amounts. Bank/Cash stay distinguishable; zero
settlements add no money. Income & Expenses can reuse payments directly, without
summing receipts as a second source of collections. Student filters can be cleared
to include all older history. Future dashboard pages reuse these same IDs/services.

## Verification

Pure file tests use disposable images/PDFs and private temporary directories.
Isolated MySQL tests use the existing guarded test schema, actual login sessions,
real bill issuance and disposable example.test users. They cover races, duplicate
guards, decisions, receipts, full-payment validation, role/ownership, CSRF, protected
files, throttle, financial-link guards and rollback. A real HTTP test starts the
same Flask app on an ephemeral loopback port against that isolated DB; it never
requires a separate demo login or writes to main records. Move-out history access
uses a controlled future clock. JavaScript uses behavioral DOM models; native
mobile rendering, focus trapping and physical Print/Save-as-PDF need browser QA.

Apply SQL/grants only with explicit approval and verified backup. No test account,
slip, fake payment or receipt is inserted into production. Keep local backup manifests,
test reports and credentials private. Detailed rollout: database/010_payments_review.md.
