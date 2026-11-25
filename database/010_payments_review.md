# Payments 010 — approval review

Applied on 09 November 2026 (Asia/Colombo) after explicit approval
`APPROVE PAYMENTS 010 SQL + GRANTS + TEST SQL + PYPDF`.
The isolated SQL/grants were applied first; full Python regression 486 tests and
JavaScript 105 checks passed, including 26 real isolated Payments tests and an actual
loopback HTTP workflow. The approved pypdf 7.0.0 dependency is installed and pinned.
Main writers were stopped for a fresh verified backup and the main SQL/grants.
Original 19 table record digests remained unchanged. Four empty new tables and exact
limited privileges were verified; no main fake accounts, bills or payments were added.
Private rollout details/manifest: `instance/payments_rollout_report.json`.
Backup restore has not been rehearsed. Do not blindly rerun this one-off migration.

Full SQL: `010_payments.sql`, `010_grant_payments_app.sql`,
`010_payments_test.sql`. Four new InnoDB tables only: payments, payment_evidence,
receipts, payment_events. No existing table ALTER, record reset or deletion.
Next number verified against existing 003–009 migrations and MySQL 8.4.7 metadata.

Issued monthly_bills.final_total is authoritative. Paid is derived from one
verified payment in the same database transaction, rather than an independently
editable bill flag. Pending is never Paid. Existing issued/void lifecycle remains.
Owner and Student bill views will display the derived payment state and receipt.

One generated UNIQUE active_bill_id covers both submitted and verified payments;
only a rejected attempt releases it for resubmission. Request keys prevent repeated
clicks. Cash cannot bypass a pending bank submission: review/reject that submission
first. A receipt is UNIQUE by payment and created atomically with verification or
Owner-confirmed cash. Owner password, throttle, current credential stamp, ownership,
bill locks and revisions protect decisions. No reversal/delete UI is included.

Zero bills use a password-confirmed Owner non-cash `zero_balance` settlement for
exactly 0.00. No transfer/slip/cash collection is fabricated. Its receipt explicitly
says no money was collected. Verified collection sums remain zero for this method.

Receipts contain immutable bill/boarding/unit/recipient/payment snapshots. Evidence
and events are append-only to the app. All timestamps UTC; dates/reporting use
Asia/Colombo. Reporting dates use decision date for reviewed records and submission
date for pending. Total Collected sums only verified amounts in the selected period.

Payments references monthly_bills directly. The existing financial-link guard blocks
bill due-date/cycle corrections as soon as any payment history exists, including
rejections. This preserves the linked evidence/history; a future reversal/settlement
policy must be approved before relaxing that protection. Bill totals are immutable.

Files: private receipts/slips directory, random names, content/signature validation,
5 MiB default upload limit (configurable up to 10 MiB), image decoding/dimension limits,
strict PDF parsing/page/object/decompression/time limits, rejection of encrypted or
active PDFs. Original bytes/hash preserved as evidence; no image recompression that
could change a signed bank document. PDF served as attachment, never embedded.
Images use authenticated inline responses with no-store/nosniff/sandbox headers.
No antivirus exists; content validation does not claim malware-free evidence.

PDF validation needs separately approved `pypdf==7.0.0` in the existing .venv plus
requirements pin. No gateway SDK or receipt-generation dependency. Receipts use
print-friendly HTML and browser Print / Save as PDF; no fabricated bank signatures.
Package documentation: https://pypi.org/project/pypdf/ and
https://pypdf.readthedocs.io/en/stable/modules/PdfReader.html

Rollout: retain a verified consistent private SQL+file backup and source checkpoint;
apply identical test schema/grants in guarded isolated DB, run isolated fixture and
regression tests, then fresh backup + maintenance main SQL/grants. Main gets only
SELECT/INSERT on four tables and five decision columns UPDATE on payments. No DELETE,
new monthly_bills UPDATE, global grants or payment amount mutation. Test account gets
fixture SELECT/INSERT/UPDATE/DELETE only on four new isolated tables. Restore has not
been rehearsed. DDL auto-commits; stop and inspect partial failures, never rerun blindly.
Rollback disables feature writes while preserving evidence/financial records. Any
DROP/restore/destructive rollback requires separate approval.
