# Expenses -> preview -> Student bills -> tracked email

The primary Monthly Bills UI is now the Student-first Invoice Builder documented
in `invoice-builder.md`. The accounting/source/delivery rules below still apply;
the earlier batch preview UI remains available only as a compatibility path.

## Owner flow

1. Income & Expenses -> Add Expense opens a centered modal. Choose Electricity,
   Water or Other. Accounting Month controls expense reporting. Expense Date is
   the actual paid date. Utility Period is
   required for Electricity/Water and explicitly shared Other expenses, and
   controls which bills use that cost. Other defaults to Owner Expense Only;
   approved 021 adds an explicit Yes opt-in and Allocation Month requirement.
   Multiple active costs in a category/utility month are combined exactly once.
   Explicit zero utilities are valid; missing costs are not silently zero.
2. Monthly Bills -> select Student/month/due date -> charges load automatically.
   This only saves draft inputs and prepares a preview; no invoice/email yet.
3. Add Other Expenses opens a centered selector of saved costs. Only explicitly
   selected Other costs are added by the Builder; legacy batch policy is separate.
   Review the amount-only invoice and any passwordless Student-specific waivers,
   then Issue & Send Invoice. A stored-snapshot ReportLab PDF is attached to the
   verified recipient's email and available through protected PDF download routes.
   Legacy batch review/send remains compatible.
   Current-month issuance is allowed once recorded costs and tenancy sources
   validate. Payment defaults to month-end; future-month issue is blocked until
   that month starts. Rent uses agreed tenancy prices and actual eligible days; utilities
   use the existing tenant-day/cent reconciliation calculator.
4. Issued snapshots immediately appear in the correct Student My Bills account.
   Student payments, Owner verification, cash and receipts continue unchanged.
5. Sent Bills shows financial/payment state independently from Email Status.
   Refresh Status to see asynchronous outcomes. Failed/Pending email can be
   retried with a one-minute cooldown and never issues another invoice.

## Historical data and corrections

Migration 020 preserves original expense names/amounts/dates and old bill amounts.
Existing expenses default to Other. Owners must explicitly categorize a genuine
legacy utility record and supply its utility month; no name-based guess is made.
Never add a second expense just to make an existing cost appear in billing.

Preparing an existing draft switches its utility source to saved expenses with an
audit event retaining the prior manual draft amounts. Issued legacy cycles keep
their frozen manual costs. First new issuance freezes all eligible allocations
and expense IDs/revisions/amounts in the cycle snapshot, even for Send One.
Changing/archiving/adding utility sources for an issued expense-source month is
blocked until the existing password-confirmed Correct Cycle workflow is used.
That voids and preserves original bills before a replacement preview; linked
payments continue to block financial correction. No receipt/debt is erased.

## Email configuration and reliability

Reuses SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM from the existing
OTP environment. Gmail uses the configured sender's appropriate App Password,
never a password in code or chat. No new dependency or mail SDK is installed.
APP_PUBLIC_URL supplies the authenticated Student bill link; local default is
http://127.0.0.1:5000, external hosts require HTTPS. Request Host is never trusted
as an email link origin. Student bill ownership checks still apply after login.

Recipient is the current active Student database email matching the invoice
snapshot, with a retired successful registration OTP marker. Inspection of
auth_email.verify_code confirmed that this marker is retired atomically only
after successful registration OTP verification. No synthetic verification flag
or arbitrary frontend recipient is accepted. Unverified/changed/invalid/non-Gmail
addresses fail safely, leaving the issued Student invoice available.

Delivery rows are created in the same transaction as invoice/lines. SMTP happens
after commit. Claims serialize concurrent workers; accepted emails cannot be
replayed by browser retry. Attempts/outcomes are append-only billing audit events.
Only safe error codes are stored, never credentials, OTPs or SMTP response text.

SMTP Accepted records server acceptance, not Gmail inbox arrival. A crash or
disconnect during DATA can be ambiguous: show Needs Review, do not blindly retry.
SMTP cannot guarantee exactly-once delivery across a network/process crash.
Review the sender's mailbox before considering any separately controlled resend.
No direct reset of Sent/Uncertain states is exposed in the UI.

After a process restart, already-authorized Pending jobs can be recovered using:

```powershell
.\.venv\Scripts\python.exe -B -m flask --app app deliver-bill-emails --owner-id <OWNER_ID> --limit 50
```

This only processes existing authorized Pending jobs and marks expired Sending
claims as Uncertain. It does not issue invoices or retry failed/accepted emails.
Normal asynchronous processing uses two bounded workers and the database outbox;
there is no distributed infrastructure or email queue dependency.

## Activation and testing

Requires separately approved database/020_* main/test SQL and grants, a fresh
verified backup and BILLING_REDESIGN_ENABLED=1 after rollout. Before activation,
legacy UI/schema paths remain compatible. No migration is executed on startup.

test_expense_billing_mysql.py uses the existing guarded isolated database with
disposable verified-marker fixtures and mocked SMTP. Its clock is moved to the
next month to verify finalized-period issuance without changing production dates.
The pre-existing suites explicitly retain their legacy billing fixture policy;
new tests exercise the activated source/month-end/delivery policy separately.
test_billing_delivery.py exercises HTML/text rendering and simulated transport
outcomes. test_billing_simple.js tests review/cancel/count confirmation and double
click behavior; native layout/focus/touch remain browser checks.

No automated test emails real recipients or creates bills for production users.
Real SMTP test messages require separate recipient approval and must be labelled
TEST / not payable. Only actual recipient confirmation proves Gmail inbox arrival.
