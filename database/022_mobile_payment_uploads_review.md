# Secure mobile bank-slip capability and Owner notification outbox

The user requested complete implementation without repeated approvals in the
direct message accompanying the mobile-upload specification. Required additive
DDL and grants are fully listed in 022_mobile_payment_uploads.sql and
022_grant_mobile_payment_uploads_app.sql. No existing table, financial amount,
account, invoice or receipt is altered/deleted/reset. No new package is required.

payment_upload_links stores only SHA-256 token digests, Student/Bill association,
credential fingerprint, request idempotency key, timestamps and consumption.
One active capability per bill, maximum 20-minute expiry; replacement revokes
the old capability. Consumption and normal payment/evidence/notification writes
commit together under the existing Student -> Boarding -> Cycle -> Owner -> Bill
lock order. Password reset/suspension invalidates the limited capability.

payment_notifications is one durable, unique email job per saved payment. Main
grants permit only SELECT/INSERT and operational columns UPDATE, no DELETE.
Test-only DELETE supports cleanup scoped to disposable fixture IDs. Failed jobs
can retry with cooldown; Sent/Uncertain cannot be automatically replayed.

Rollout: preserve source/Git checkpoint; verified fresh SQL/private-file backup;
apply matching isolated SQL, run security/functional tests with mocked SMTP;
briefly stop verified main process; fresh backup; main DDL/grants; verify every
original table digest and exact grants; enable MOBILE_SLIP_ENABLED and restart.
DDL auto-commits; no automatic DROP/restore on a partial error. Inspect any error
before retry. Restore rehearsal is not implied by a hash-verified backup.

MOBILE_PUBLIC_BASE_URL (or PUBLIC_BASE_URL) must be a phone-reachable HTTPS origin.
No tunnel, public binding or external account is created automatically. Without
configured HTTPS, the UI explains the blocker and preserves desktop upload.
No live WhatsApp messages or actual test emails are sent. Mobile reachability
requires real phone/HTTPS verification and is not claimed by isolated tests.
