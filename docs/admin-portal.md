# Platform Admin — UC31, UC32, UC33

Uses the existing main Flask app, normal `/login`, revocable auth_sessions and Email OTP/reset infrastructure.
The UI contains exactly Dashboard, Manage Users, Boarding Listings, Platform Reports and Log out.
No public Admin registration, role editor, financial access, user deletion or listing deletion is added.
The approved OOAD diagram was not present in the workspace; supplied UC31–33 requirements define scope.

## Security and integration

- Every `/admin/...` handler resolves the current active Admin account from MySQL.
- Critical POST actions require CSRF, a fresh throttled Admin current password, explicit confirmation,
  a revision match, current actor/session revalidation under locks, and an atomic state/audit commit.
- Passwords are never returned in form values, logged or stored in browser storage.
- `users.admin_suspended` is independent from `users.is_active`. Suspend revokes every target session and
  retires outstanding reset grants. Reactivate only removes the Admin restriction and requires fresh login.
- Existing login, request authorization and password-reset writes reject suspended accounts. No tenancy,
  bill, payment, maintenance, bank, room or price record is automatically modified by account decisions.
- `boardings.admin_hidden` is independent from Owner draft/published. Discovery, direct Student details,
  published cover retrieval and new join-request writes enforce it on the backend. Owner edits/republishing
  do not assign it. Restore does not publish a draft. Owner Profile/Listing Preview explain the block.
- Admin suspension does not silently hide a listing. Existing ordinary inactive-Owner public restrictions
  are preserved. Administrators use the separate Hide Listing action when moderation is needed.
- Tenant-authorized My Boarding/history remain available under existing rules; they are not public discovery.
- Report queries read only users, boardings and minimal Admin audit decisions. No financial tables are used.
  Student/Owner totals exclude Admins. Listing groups are mutually exclusive: Visible, Hidden, unhidden Draft,
  or unhidden Published with independently inactive Owner. Monthly boundaries use Asia/Colombo and UTC storage.
- Existing schema lacks a per-account email-verification timestamp. Details state this limitation explicitly.

## Approved database rollout

`database/016_admin_portal.sql` and `016_grant_admin_portal_app.sql`.
Review/backups/rollback limits: `database/016_admin_portal_review.md`.
Feature flag: `ADMIN_PORTAL_ENABLED=1`, enabled only after approved main SQL and isolated tests.
Never disable the enforcement code/flag once real suspension or hide decisions exist.

## First Admin provisioning — separate explicit approval required

On a fresh installation or an upgraded database without an Admin, run the
interactive command after approval to create the first Admin.

```powershell
Set-Location -LiteralPath E:\SmartBoardingSystem
.\.venv\Scripts\python.exe -B -m flask --app app provision-admin --approved
```

Enter the approved Admin full name and an unused Gmail address at the local prompt. Enter a strong password
twice using hidden input. The existing Email OTP service sends one verification code to that approved address;
enter the code at the hidden prompt. Do not paste passwords or OTPs into chat, arguments or `.env`.

The command refuses to operate without `--approved`, refuses existing email addresses, and refuses to create
another Admin when one already exists. A MySQL advisory lock serializes the first-Admin command. It uses the
existing password policy/hash function and challenge expiry/attempt rules. Because the legacy challenge
pending_role ENUM allows Student/Owner only, NULL is reserved for this local flow. Public web verification
cannot consume that challenge; only the explicitly invoked local command can create the verified Admin and
its audit event in the same transaction. No auth schema migration or second login system is needed.

Successful provisioning does not log anyone in. Open `http://127.0.0.1:5000/login`, sign in normally and reach
Admin Dashboard. Account creation and OTP delivery must not run before approval of the privileged action.

## Verification and manual review

The release QA backup includes Admin access, moderation, audit and sidebar tests.
The write tests use disposable accounts in an isolated database.

Manual main check after provisioning: Login → Dashboard → Manage Users → View Details. Check filters and the
centered dialog, keyboard Escape, eye button, Light/Dark and mobile menu. Do not suspend a real user or hide a
real listing merely to test without separate authorization. Use the isolated automated write workflow instead.
