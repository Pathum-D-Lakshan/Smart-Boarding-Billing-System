# Student My Bills and My Payments

The existing Monthly Bills, Payments, Owner Settings/bank destination, evidence
storage and receipt services are reused. No schema/grant/dependency change.
No gateway, automatic bank verification, installments, separate charge bills,
new tenancy model or duplicate collection table is introduced.

## My Bills

Existing `/student/bills` now shows three real global Student summaries: current
issued-bill count, unpaid outstanding amount (including submissions under review),
and verified settlements with receipts. The Paid Bills count includes verified
zero-balance settlements; these do not represent currency collected.

Bill history includes the existing Void records without pretending they are payable.
Search covers reference and stored billing month; status/sort/page use allowlists
and prepared SQL. Only the authenticated Student's rows are returned. Pagination
and eligible-bill selection use set-based queries, not per-row financial lookups.

Debt and evidence status are separate: an overdue bill stays Overdue while its
payment is Pending Verification. A rejected attempt remains in history and does
not settle the debt. No new persisted Paid/status flag exists; the views project
the same authoritative verified payment/receipt records used by Owner services.

`GET /student/bills/<bill_id>` returns an authorized full page or the existing
`X-Payment-Modal: 1` JSON/HTML fragment for a centered native dialog. It displays
issued line items and saved allocation/days/agreed rent, never current room prices.
Print/View Issued Bill opens a separate print-friendly page; opening or printing
does not write a payment or receipt. Print remains an explicit user action.

## My Payments and submission

Existing `/student/payments` shows Pending Verification, Verified and Rejected
counts, searchable/filterable/paginated history, protected detail dialogs and
verified receipt links. Student date filters now default to all history; Owner
current-month defaults remain unchanged. Summaries follow date/method filters.

`GET /student/payments/submit` is a read-only chooser over actual eligible owned
bills; optional `bill_id` is reloaded through the existing ownership-checked service.
The existing `/student/bills/<bill_id>/submit-payment` GET/POST remains the canonical
submission route. Both chooser and selected form enhance to the same centered
dialog, with ordinary full-page links/forms when native dialogs are unavailable.
Bill selection is GET; financial writes use native multipart POST with CSRF and a
fresh idempotency key. A duplicate/uncertain write never automatically retries.

Selected form shows one exact read-only amount, full-transfer requirement, actual
Owner bank instructions, date, required transfer reference, optional sending bank
and note, and the existing protected slip upload. No combined multi-bill payment.
Copy Account Number requires an explicit click; leading zeros remain strings.
If clipboard access is blocked, the field is selected for manual copy. No account
number/password is stored in localStorage or copied automatically.

Missing/unrelated bank instructions now block both UI and direct POST. The guard
runs before parsing evidence and again within the existing locked transaction.
Owner bank-setting writers share the Owner lock, preventing a concurrent removal
from bypassing that final check. Existing pending-key idempotent reads still return
the same record rather than making a second payment. A real transfer always needs
the Owner's independent review; the app does not know whether a transfer reached a bank.

Zero-total bills require no transfer or slip. Only the existing explicit Owner
zero-balance settlement issues its non-cash receipt; it records no money collected.
Scheduled or moved-out status alone does not hide a genuine issued financial record.

## Evidence, decisions and receipts

Existing `payment_files.py` validates size, extension and actual JPG/PNG/PDF content,
using private generated filenames outside static files. Existing PDF worker limits
pages/active content/resources. Format validation does not prove malware absence.
No antivirus dependency was installed. All existing slip routes verify bill/student
or Boarding/Owner scope, integrity hash and safe no-store/security headers. PDFs
are downloaded rather than embedded as active page content.

Owner Verify/Reject/password/atomic transaction logic is unchanged. Rejected
evidence and record remain; a correction creates a new attempt. Resubmit is enabled
only if the current bill remains eligible. Verified, submitted and zero bills cannot
receive another transfer. Pending/rejected submissions have no verified receipt.

Receipts reuse the existing immutable snapshot/hash and authorized print-friendly
page. Print/Save as PDF uses the browser; no dedicated receipt PDF endpoint/generator
was added. ReportLab reporting PDFs are a different existing module. No bank stamps,
digital signatures or automatic bank assurances are invented. Owner collections/
Reports continue deriving verified Payments once; no new income record is written.

## Verification

`test_student_finance.py`: five pure view/filter tests. `test_student_finance_mysql.py`:
13 actual isolated MySQL checks covering summaries, immutable breakdowns, dates,
bank gating, selected-bill scope, multiple genuine monthly bills and pagination,
pending/reject/resubmit/verify, moved-out history, zero settlement and financial access.
Existing 26 payment tests and the complete regression suite preserve upload/CSRF/
Owner password/concurrency/rollback/receipts/Finance/Reports coverage.

The existing actual HTTP test now verifies Bill/chooser modal fragments and the
Student upload -> Owner reject -> Student corrected upload -> Owner verify ->
Student receipt flow on the same Flask app with disposable isolated records.
Fixture bank destinations exist only in the approved isolated schema; Settings
tests explicitly keep their original unconfigured-bank starting state.

JavaScript DOM models cover centered dialogs, error recovery, duplicate POST
prevention, native Student bill selection and clipboard/manual-copy fallback.
They are not native visual/mobile/focus tests. Main HTTP/query checks remain
read-only and do not create fake production transactions or accounts.

## Manual main review

Use Owner at `http://127.0.0.1:5000` and Student at `http://localhost:5000` for
independent sessions. Ctrl+F5 -> Student My Bills -> View Bill -> inspect saved
breakdown -> Submit Payment -> verify exact bill/destination and upload only a
genuine transfer's slip -> Owner Pending Payments -> independently check bank and
Verify with password -> Student refreshes My Bills/My Payments and opens receipt.
Do not verify a test slip as real money or generate fake main transactions merely
to demonstrate this flow. If main has no eligible bill/bank instructions, verify the
honest empty state; the complete write workflow was exercised on isolated data.
Review both themes, mobile/sidebar, centered dialogs, keyboard close and print.
