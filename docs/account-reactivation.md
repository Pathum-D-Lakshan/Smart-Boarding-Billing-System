# Restricted account access and reactivation — UC31

This extends Manage Users, not the Admin Sidebar/use-case list. No separate login system,
external email provider, dependency, production test account or business record deletion is added.

## Authentication and scope

Normal Login checks the password before explaining suspension. Wrong credentials retain the existing
generic message. Correct suspended Student/Owner credentials create only a 15-minute restricted
auth_sessions row (`session_scope='restricted'`, current suspension event, credential stamp, no Remember Me).
The signed browser cookie has `restricted_account`, not normal `user_id`/`auth_session_token` authorization.
Session/CSRF state is rotated and the prior token revoked. Existing registration Email OTP remains unchanged;
the current Login has no separate OTP/MFA step to bypass.

Normal auth_sessions validation enforces `session_scope='normal'`. `load_current_account` rejects restricted
identity even if normal keys are present. A global restricted-route guard allows only Login, Logout,
static assets and the restricted dashboard/appeal/acknowledgement endpoints. Billing, payment, settings,
Owner/Student/Admin and direct API/business routes are denied. Account/session/suspension/credential state
is rechecked from MySQL. Expiry, logout, password changes, new suspension events and reactivation invalidate
restricted access. Approval never upgrades it: the user must perform a fresh normal Login.

## Workflow and data

`/account/restricted` shows the verified account's current suspension event and user-visible explanation.
Existing internal-only `admin_events.reason` is never used as a public explanation. Migration leaves old
events' `user_visible_reason` NULL; those explicitly show that no public explanation has been recorded.
New Admin suspension forms warn that their explanation is user-visible, and insert it in the separate field.
No historical private reason is automatically backfilled or exposed.

Originally 017 allowed one lifetime appeal per user/suspension event. The separately approved 018
change allows a new request after rejection, preserving each historical request and decision. A generated
pending-event UNIQUE key permits only one Pending request per user/suspension. A required 1–1000-character message,
CSRF and an account-keyed 5-attempt/15-minute submission limit protect the form. Identity/role/target
are taken from the restricted server context, never browser-submitted IDs. Pending does not mean Active.
Rejection retains suspension. With ACCOUNT_REACTIVATION_RETRY_ENABLED enabled after 018, the restricted page
shows the reason and Request Again. A retry must identify the latest rejected request actually reviewed;
stale forms and duplicate Pending requests are rejected under the user lock. Previous requests/audits
are never reused or erased. The same rate limit applies to retries. Without the flag the original 017
policy remains active. A new suspension has a new event and can have a new appeal. Reads/Login never
create an appeal automatically. The latest 20 requests for the current suspension are visible in history.

Manage Users has All Users / Reactivation Requests tabs, real status counts, status/search/pagination,
centered review/confirmation dialogs and the existing password Show/Hide controller. Decisions require
Admin role/current account/session, CSRF, existing password-attempt limits and explicit confirmation.
Locks follow actor → target user → request; the current event/status/revision are revalidated.
Approval updates the request, clears only admin_suspended, revokes restricted tokens and records an
existing account audit + new appeal audit in one transaction. Rejection leaves account status unchanged
and records its mandatory user-visible explanation. Audit failures roll everything back. Concurrent,
duplicate or old-event decisions return a conflict instead of activating another suspension.

The request queue defaults to All with Pending first, so completed requests no longer disappear from
the default list. Admin Dashboard and User Details link directly to requests. Explicit Pending/Approved/
Rejected filters remain available. The same backend paths handle Student and Boarding Owner accounts.

Manual Reactivate preserves its previous behavior and atomically approves a Pending current-event appeal
with a manual-action note. A rejected historical request remains historical if Admin later manually
reactivates without a Pending appeal. Independent users.is_active=FALSE is never overridden by this feature;
appeal approval reports that restriction instead of silently changing it.

On the next fresh normal Owner/Student Login, unacknowledged approval notices are loaded by the current
user's ID. `Got It` is a CSRF-protected POST that persists acknowledged_at and an append-only audit event.
Simply viewing in another browser does not dismiss it. Rejected users can acknowledge with `Understood`
in restricted mode; the request status/reason remain visible afterward. No decision/audit history is erased.

## Time and schema

Existing Admin/appeal timestamps are UTC DATETIME(6). Display converts once to the project's existing
Sri Lanka UTC+05:30 timezone (Asia/Colombo for the system's modern dates), including cross-day boundaries.
It does not append an offset to an unconverted UTC time or require Windows tzdata installation.

Approved 017 SQL/review: database/017_account_reactivation_review.md. Adds two small request/audit tables,
scope/event columns on existing auth_sessions, and an optional public-reason field on existing admin_events.
Defaults preserve all existing normal sessions, audits, user flags and records. Main request UPDATE is
column-limited; appeal audit is SELECT/INSERT only. Test DELETE grants are isolated fixture cleanup only.
Activation flag `ACCOUNT_REACTIVATION_ENABLED=1` requires both 016/Admin controls and revocable sessions.
Never disable scope enforcement as a rollback after restricted sessions exist. No main fake appeals or
decisions are needed to validate the feature.

## Verification

`tests/test_account_reactivation.py`: mocked credential privacy, context separation and actual time conversion.
`tests/test_account_reactivation_mysql.py`: isolated Student/Owner restricted Login, expiry/logout/stamp,
Pending/Approve/Reject/manual compatibility, CSRF/password/role isolation, cross-user acknowledgement,
stale/new events, concurrent decisions/submits, rate limits, rollback and actual HTTP with the same Flask app.
`tests/test_reactivation_finance_mysql.py`: issued/paid bills, receipt, contracts and saved prices survive
appeal rejection/manual reactivation. Existing Admin dialog JS is reused and its appeal field/action tested.
These tests do not claim native browser visual/focus/mobile verification.

Manual check on main: a legitimately suspended account's correct credentials → restricted page; verify
current date/time/public explanation. Submit an appeal only when intended → Admin Manage Users →
Reactivation Requests → Review → Approve/Reject with current password. After approval log in again normally
and dismiss `Got It`; after rejection acknowledge `Understood` and verify business access remains blocked.
Do not suspend a real user or make a fake request merely for testing without explicit approval.
