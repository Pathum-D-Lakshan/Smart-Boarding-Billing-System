## Approval scope

Review the complete SQL in `007_create_auth_sessions.sql`,
`007_grant_auth_sessions_app.sql`, and `007_create_auth_sessions_test.sql`.
These scripts have not been executed. Existing business/authentication tables and
their records are not modified. No database or account is recreated.

## Login policy

- Normal login: browser-session cookie, maximum 8 hours on the server.
- Keep me signed in: persistent cookie, maximum 7 days; no sliding extension.
- Both use the existing Flask signed HttpOnly, SameSite=Lax cookie. Production
  HTTPS configuration enables Secure; local HTTP remains usable.
  Set `APP_ENV=production` (or `SESSION_COOKIE_SECURE=1`) behind production HTTPS.
- Each login creates a random 256-bit token. MySQL stores only its SHA-256 digest
  and a digest of the existing password stamp, plus expiry/revocation metadata.
- Token rotation on successful login revokes the current browser's older token
  in the same transaction. CSRF/session state rotates after successful login.
- Every authenticated request checks the active account, current role, password
  stamp and unexpired/non-revoked session. Password reset invalidates sessions
  through the changed credential stamp, including cookies captured earlier.
- Logout revokes the current token before clearing the cookie. If revocation
  cannot be confirmed, show an error with Retry rather than claiming success.
- Passwords/tokens are never stored in localStorage or logged. Remember Email
  stores only the explicitly opted-in email; Theme stores only light/dark.

## Backup and rollout

Before DDL, create a fresh consistent read-only snapshot of all current production
tables and a cover archive under ignored `instance/backups/`. Verify SHA-256 and
ZIP integrity. Backups contain private authentication data and stay local.
Record the migration hashes and metadata baseline in the backup manifest.
First apply the approved isolated-schema script and run real tests. Only then
apply the approved production CREATE and table-scoped grant. Verify existing
tables/records remain unchanged before enabling the feature flag.

`AUTH_SESSION_STORE_ENABLED` stays disabled until schema/grants are approved and
verified. Enabling it requires existing signed-in users to log in once again;
legacy cookies are not silently accepted as revocable sessions.

## Failure / rollback

MySQL DDL auto-commits. Stop and inspect any partial failure; do not rerun CREATE
blindly or hide mismatches with IF NOT EXISTS. A UI rollback can preserve the
additive table/history and keep server-side revocation checks enabled. Do not
restore the legacy cookie-only authentication path after activation: an emergency
authentication rollback needs a coordinated session invalidation/signing-key
review first. It does not require deleting users, requests, tenancies or session
records. Any DROP, REVOKE, key rotation or backup restore needs separate approval.
A restore must first target an approved empty recovery database, never overwrite
the live database. Backup restore has not yet been tested.
