# QR-first mobile bank-slip upload

This extends the existing manual full-invoice bank-transfer payment flow. There
is no gateway and a slip never marks a bill Paid. Owner password confirmation,
independent receipt of funds and the existing atomic receipt transaction remain
required. Existing desktop upload continues to work.

## Student and Owner workflow

1. Student → My Payments: four sequential sections show Your Bill, Bank Transfer
   Details, Upload Payment Slip and Payment History. The full invoice opens via
   View Full Invoice rather than permanently occupying the main page.
2. View Bank Details opens the actual boarding-scoped account and Copy Account
   Number / Copy Amount actions. Missing details show one Owner Settings → Bank
   Details instruction. Scan QR Code uses a CSRF-protected POST, checks the live
   HTTPS origin before minting a token, then opens a compact centered QR modal
   with a countdown, Copy Upload Link and Refresh QR. No phone number is needed.
   An already-paid Student can submit proof even when the Owner has not published
   bank instructions. For new transfers, ask the Owner for the correct account.
   Upload from Computer opens the same evidence submission flow. QR is
   rendered locally with ReportLab and Pillow; no external QR API gets the token.
3. Scan the QR with your phone camera. Alternatively copy the secure link, or
   Share via WhatsApp, select the contact and press **Send manually**. This
   application neither automatically sends nor claims WhatsApp delivery.
4. Phone: open link → allow camera permission → live rear-camera preview → Take
   Photo, or use the native Phone Camera / Gallery fallback →
   review the selected image → **Confirm & Save**. Before submitting, **Delete Slip**
   clears the local selection, resets the camera/gallery inputs and permits a
   replacement. Nothing is saved to the server until Confirm & Save. After
   submission, use Delete Submission in the signed-in My Payments page while
   the slip is pending. The phone upload link only submits a slip.
   Use a clear JPG/PNG or static PDF
   within the existing 5 MB limit. HEIC, executable or active PDF files are not
   accepted. A replacement photo does not submit until explicitly confirmed.
5. Submission becomes Pending Verification in the existing Student and Owner
   Payments screens. Owner sees the protected evidence and independently
   verifies/rejects the full transfer. Verification creates the normal receipt;
   rejection preserves evidence and permits a fresh corrected submission.

## Required phone-accessible HTTPS setup

The main portal stays on `127.0.0.1:5000`. An approved temporary HTTPS endpoint
uses a path-limited gateway to expose only the mobile upload endpoints. Verify
the public address before demonstrating QR upload. See
[mobile-upload-demo.md](mobile-upload-demo.md) for the actual browser workflow,
first-visit **Enter site** warning, 60-minute free-session limit and safe
start/stop commands. Physical-phone scanning/camera has not been verified.

Use an existing trusted HTTPS deployment/reverse proxy with a valid certificate
and an origin reachable by the phone. Do not expose MySQL or Flask debug mode.
The proxy should expose only these paths for a limited upload demonstration:

```
/mobile/payment-slip
/mobile/payment-slip/open
/mobile/payment-slip/save
/static/css/mobile-payment-slip.css
/static/js/mobile-payment-slip.js
```

Forward them to the existing `http://127.0.0.1:5000`, preserving paths. Reject
other public paths. Set an upload-body limit of at least 6 MB. The TLS proxy
must **overwrite**, rather than append/trust client input for,
`X-Forwarded-Proto: https`. Keep Flask bound to 127.0.0.1. A public tunnel or new
proxy installation requires explicit approval. The limited demonstration setup
was approved; it adds no automatic startup service or public debug mode.

After obtaining the actual HTTPS origin, set locally (do not post secrets):

```dotenv
MOBILE_SLIP_ENABLED=1
MOBILE_PUBLIC_BASE_URL=https://YOUR-ACTUAL-HTTPS-HOST
MOBILE_TRUST_LOCAL_PROXY=1
```

`MOBILE_TRUST_LOCAL_PROXY=1` is appropriate only for a trusted TLS proxy on the
same laptop; the upload endpoint accepts the forwarded scheme only when the
socket peer is 127.0.0.1/::1. Direct TLS deployments do not need this option.
Waitress trusts only the loopback proxy's forwarded HTTPS scheme; no forwarded
host/client identity is trusted. `PUBLIC_BASE_URL` is a fallback if the
dedicated mobile origin is absent. HTTP, localhost, loopback, user-info, paths,
query strings and fragments are refused as mobile origins.

Restart the verified existing main process after editing configuration:

```powershell
cd E:\SmartBoardingSystem
.\tools\restart-main-server.ps1
```

Do not launch a second competing server on port 5000. Generate a **new** link
after configuration. Test phone HTTPS reachability before claiming WhatsApp
upload is ready. The application deliberately refuses insecure phone upload.

## Capability and evidence security

- Cryptographically random 256-bit bearer, SHA-256 digest only in MySQL.
- Raw token travels in the URL **fragment**, then in an HTTPS POST body; it is
  immediately removed from browser history, never in a query/path/access log.
- Dedicated HttpOnly/Secure/SameSite=Strict, path-scoped cookie. It grants only
  one bill's upload operation, not Student/Owner portal authentication.
- Fifteen-minute server expiry; replacement revokes prior links. New records expire
  at creation + 900 seconds, and legacy longer-lived rows are also capped at fifteen
  minutes when validated. Earlier five-minute records keep their stored expiry.
  The existing SQL CHECK has a twenty-minute upper bound;
  this stricter runtime policy needs no migration. Cookie and client expiry are
  bounded by the remaining time. Hash binding
  covers Student, invoice, password credential fingerprint and request key.
  Reset/suspension/inactive accounts, issued-bill changes, pending or verified
  payments are rechecked. A conflicting signed-in identity is rejected.
- Existing Student→Boarding→Cycle→Owner→Bill locks, then token lock, serialize
  competing mobile/desktop/cash submissions. Evidence, token consumption,
  pending payment, audit and notification queue commit together. Failure rolls
  back and removes only files confirmed not referenced by a committed record.
- Exact configured Origin, capability CSRF, request-size and shared database
  rate limits. No cross-origin access, external page assets or referrers.
- Existing file-content/decompression/PDF checks. Mobile photos are oriented
  then re-encoded from pixels without GPS/EXIF/PNG metadata or resizing; the
  exact sanitized saved bytes are hashed. Desktop original evidence is retained.
  Saved slips stay outside static files and require scoped authenticated access.
- Optional bank transfer ID is preserved. When omitted the reference explicitly
  identifies the invoice; it does not fabricate a bank transfer ID.

## Owner Gmail notification

The same transaction queues one job per new slip, including existing desktop
submissions while enabled. Notification is addressed only to the appropriate
active Owner's OTP-verified Gmail. It attaches the saved integrity-checked
evidence and links to authenticated Owner Payments. SMTP uses existing settings
and TLS; no package or gateway is added.

Email failure does not roll back or approve the payment. Owner Payment Details
shows notification status and a CSRF-protected retry with one-minute cooldown.
Sent means SMTP acceptance, **not verified inbox delivery**. Sending interrupted
over five minutes becomes Uncertain on the next queue recovery; it is not blindly resent.
Pending jobs can be queued from their existing Owner Payment Details after a
server interruption. An operator can also recover pending jobs with
`.\.venv\Scripts\python.exe -B -m flask --app app deliver-payment-notifications --limit 20`.
This command sends real pending operational notifications, so it is not run as
a test against main data. No real test email or WhatsApp message is sent by QA.

## Schema and rollout

022 adds `payment_upload_links` and `payment_notifications` only, with limited
table/column grants. No original records/tables/amounts are modified or deleted.
Full SQL: `database/022_mobile_payment_uploads.sql`,
`022_grant_mobile_payment_uploads_app.sql`, `022_mobile_payment_uploads_test.sql`.
Review: `database/022_mobile_payment_uploads_review.md`.
Backups are hash-verified private SQL and evidence archives. Restore rehearsal
is not claimed. DDL auto-commits; on a partial error inspect rather than drop or
blindly reapply. Disable `MOBILE_SLIP_ENABLED` to roll code back while retaining
submitted payments and evidence. Do not delete capabilities or email audit rows.

## Short main-system manual test

With real HTTPS configured, use an actual authorized Student with an issued
unpaid bill and saved Owner bank settings: choose invoice → copy/check bank
details → Scan QR Code → scan the laptop QR with your phone → take a clear
slip photo → Confirm & Save. It must show Pending Verification on phone and in
both portals. Reopening the same link must refuse another upload. Owner checks
actual funds before verifying with their password; Student then sees Paid and
the existing receipt. Separately confirm the Owner Gmail inbox, not just SMTP.
Do not fabricate bank evidence or production payment records for testing.
