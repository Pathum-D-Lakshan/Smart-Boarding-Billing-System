# Mobile QR demonstration

Keep the laptop awake and online while the approved temporary HTTPS tunnel is active.
The main portal remains http://127.0.0.1:5000; do not use the public origin to log in.

1. On the laptop, hard-refresh My Payments with Ctrl+F5.
2. Select an issued unpaid invoice, then click **Scan QR Code**. The actual
   Student login generates the QR; no WhatsApp number is needed.
3. Scan with the phone. On the provider's first-visit warning, press **Enter site**.
4. Allow camera access, take a photo or choose Gallery, then review it. **Delete
   Photo** clears the selection before submission. **Confirm & Save** submits
   once as Pending Verification; it does not mark the invoice Paid.
5. If bank details are unpublished, ask the Owner for the correct destination
   before making a transfer. The Student can still submit a slip for a transfer
   already made. The Owner opens **Payments → Pending Verification** to inspect
   the slip and check the transfer. After **Confirm & Verify**, the Student sees
   **Payment Approved** and a receipt link on Dashboard and My Payments.

The individual QR/link lasts fifteen minutes and can submit once. **Share via
WhatsApp** only prepares a message: the user must press Send manually.

## Restart after the free tunnel expires

Pinggy's free tunnel lasts 60 minutes. After it ends, run from PowerShell:

```powershell
cd E:\SmartBoardingSystem
.\tools\start-mobile-upload-https.ps1 -Approved -Provider Pinggy
```

This reuses a still-running session or creates/configures a fresh HTTPS origin
and safely restarts the main app on approved Waitress 3.0.2 (loopback only,
debug disabled). Refresh My Payments and generate a new QR. QR creation checks
actual HTTPS reachability and the configured application identity before
creating/revoking a token. A down tunnel shows an unavailable message with
Upload from Computer instead of a known-dead QR. That option uses the native
file picker on the current computer or phone and works without the tunnel.
It does not migrate the database or create a payment. It uses the existing
Windows SSH client and workspace identity; no paid service is installed.

Read-only reachability checks:

```powershell
.\.venv\Scripts\python.exe -B tools/verify_mobile_https.py
```

Stop the temporary public upload endpoint and restore prior mobile settings:

```powershell
.\tools\stop-mobile-upload-https.ps1
```

Only the recorded tunnel and gateway are stopped. Main stays local. Never
share generated upload links in logs or screenshots; they are bearer access.

Phone scanning/camera and real email receipt have not been tested on a physical
phone by automated QA. Owner Payments must show Pending Verification after
the real user's submission; the Owner must independently verify actual funds.
