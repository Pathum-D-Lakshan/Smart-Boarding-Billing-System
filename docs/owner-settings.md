# Owner Settings

Existing main-app shared Owner layout, Dark Navy/Cyan and Sky Blue Light themes.
Settings Home has exactly four links, not four expanded forms: Account Settings,
Security Settings, Bank Details and Appearance. Every form is a separate protected
page with Back to Settings. No new Student Dashboard, payment gateway, 2FA or email
change workflow is introduced.

## Entry and write authorization

Normal sidebar entry `/owner/settings` always clears the previous grant and shows
Access Settings with current password, eye, Cancel and Continue. Successful CSRF
POST `/owner/settings/access` uses the existing current-Owner password check and
shared database 5-failure/15-minute throttle. A signed-session grant lasts a fixed
300 seconds, bound to user, credential stamp and current login/CSRF binding. It is
not a plaintext password or an independently reusable browser verification flag.
Direct Home/form GET/POST checks the same active Owner/session/grant; missing,
expired or altered bindings require re-entry. Back to Settings uses `/home` within
the same authorization; clicking the sidebar again demands fresh verification.
Logout/login clears session state, and password/role/session changes invalidate
the binding. Responses use no-store/nosniff.

Every actual save independently checks current password again, then rechecks the
credential stamp, active Owner and live login under locks. Merely unlocking cannot
authorize later writes without a password. Browser IDs/verified flags are ignored.
Forms use CSRF, bounded input, prepared SQL, revisions and atomic audit. Competing
or stale updates produce a conflict. Account/Bank/Appearance Save opens one centered
confirmation; Security already has Current Password and does not ask twice.
Password retries are blank/editable with other inputs preserved. Native page/form
fallbacks remain for account/security/bank operations. No passwords enter storage,
URLs, audit, rendered values or logs. Database errors log errno only.

## Account

Full Name remains in existing users.full_name (150 characters). Personal phone is
new Owner-only settings data, normalized to +94 format; local 0-prefix, 9-digit and
+94 input are accepted. The form loads actual saved values. It never invents a
personal phone by copying the Boarding's public contact. Email is read-only and
submitted email/role/user_id cannot change account identity. Redirect reloads the
real account so shared Header/Profile shows the updated name immediately.

## Security

Current/New/Confirm fields have independent Show/Hide buttons. Existing 8-128
character plus symbol policy and hash implementation are reused; mismatch/weak/
current-password reuse are rejected. Password change, all-session revocation,
retirement of current reset authorizations and minimal audit commit atomically.
This includes Keep Me Signed In sessions. The current browser is safely signed
out, consistent with the existing reset flow, and must use the new password.
Challenge -> Owner -> Session lock order follows reset/login; errors roll back
password, session revocations and reset retirement together.

## Bank Details and Student Payments

One current bank instruction per Owner/Boarding: Bank Name (100), Account Holder
(150), Account Number (6-34 digits), Branch (100). Leading zeros are preserved.
Every save derives/locks the owned Boarding; submitted IDs are ignored. No Boarding
means a clear setup prompt, not an invented association. A saved number is masked
by last four on Settings; a blank replacement keeps it. No banking password/PIN/
card fields. Audit records relevant bank metadata, last-four and keyed fingerprint,
never the full number or credentials. Existing bank data remains after reload.

Student bill/payment pages reuse the existing authenticated bill scope. Full
destination information is disclosed only for that Student's own issued, positive,
currently payable bill and the matching Boarding/Owner bank record. Other Student
bills, public listings, Owner bill responses and invalid/non-payable bills do not
expose it. Missing configuration asks the Student to contact the Owner; it does not
rebuild/block the existing slip-submission workflow. Transfer occurs externally,
then slip upload -> manual Owner verification -> existing receipt. Settings never
verifies a payment, changes a bill or creates financial records.

## Appearance

The shared `window.SmartBoardingTheme` API wraps the same existing
`smartboarding-theme` preference. Preview changes the current page only; Cancel
restores the saved preference. A password-verified Settings POST approves the
allowlisted choice, and the response applies/saves it through that shared API once.
No parallel server theme source is read or created. An audit event records the
confirmed preference action. If storage is blocked, the page reports that the
theme could be applied but not persisted. JavaScript is needed for browser theme
preview/persistence; other sensitive forms retain native fallbacks. Header toggle's
existing non-sensitive save behavior remains unchanged. Theme values alone are
stored locally; Settings authorization and account/bank data are never stored there.

## Database, integration and checks

Approved additive 013: owner_settings and append-only owner_settings_events. No
ALTER/reset of existing tables. App SELECT/INSERT on two new tables and UPDATE
only eight operational settings columns; no DELETE/identity/audit mutation grant.
Original users/auth tables retain their existing privileges and fields.
Full SQL/rollout constraints: `database/013_owner_settings_review.md`.

Owner -> Session -> Settings locks guard normal writes; Bank adds the Boarding
lock first. Password change locks any reset challenge before Owner, matching reset.
Revision/audit commit is atomic. GETs do not create settings rows. Names/contact,
bank instructions, password and appearance events have a single consistent revision.

Tests use only the approved isolated schema/disposable accounts. Coverage includes
gate/direct routes/expiry/binding/logout/role/CSRF, field limits, header refresh,
bank ownership/masking/private audit, Student bill instructions, password policy,
Remember Me revocation/reset retirement/new login, rollback/races and actual HTTP.
DOM-model tests cover modal/eye/retry/native POST, appearance preview/cancel/save,
graceful fallback and sensitive back-forward restoration. Native browser visual
appearance is a separate manual check and must not be inferred from those models.

Manual main check: Owner Settings -> password -> four cards -> Account -> edit
name/phone -> Save -> confirmation/eye -> refresh. Bank -> actual instructions ->
save -> mask remains; authorized Student payable bill displays the same destination.
Appearance -> preview -> Cancel restores; preview -> save/password persists.
Security password change signs out all sessions; log in again with the new password.
Do not create fake main account/bank/payment records to demonstrate these steps.
