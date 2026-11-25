# Simple Student Settings

Student Settings has exactly three navigation cards: Account Settings, Security
Settings and Appearance. It reuses Owner Settings CSS, password/illustration macros,
native gate/confirmation controller, theme API, five-minute session binding and
role-scoped database password-confirmation limits. No Student photo/academic/bank/
notification/session-management UI is included. Screenshot extras are not scope.

## Routes and authorization

- GET `/student/settings`: fresh current-password entry; always clears the prior gate.
- POST `/student/settings/access`: CSRF, current active Student, existing hash check,
  role-scoped five-failures/15-minute throttle; issues a five-minute signed-session
  grant bound to Student ID, login token, CSRF and credential stamp.
- GET `/student/settings/home`: three cards and no forms.
- GET/POST `/student/settings/account|security|appearance`: only the selected form;
  direct routes require the live gate. Save separately verifies current password.

Student gate keys are separate from Owner keys, but use the same verification
implementation. No plaintext passwords or client-only authorization flags. Settings
responses are no-store/nosniff. The shared controller clears credentials and hides
sensitive content on navigation; bfcache restoration reloads for server revalidation.
The sidebar starts at the access gate, while Back/Cancel use the gated home route.

## Storage and transactions

Approved 015 adds only nullable `users.contact_phone` and append-only
`student_settings_events`. Existing name/email/hash/identity remain on users.
Phone is optional; supplied local/9-digit/+94 formats normalize to +94. Full Name
is 1–150 characters, one line. Email is read-only and ignored in submitted values.
Only the authenticated Student's allowed columns may update. IDs/role/tenancy/
bank fields from forms are never used to choose a target or applied to accounts.

Account and Appearance saves use a centered Confirm Changes password dialog.
Security has one Current Password plus New/Confirm fields, with no second prompt.
Password policy/hashing is unchanged; reuse is rejected. Security locks existing
reset challenge -> Student user -> auth session, matching the existing policy.
A successful password change atomically revokes all login/remember sessions,
retires reset grants, records a safe audit event and signs the current browser out.
The next login/Settings entry must verify fresh credentials.

The locked users row serializes latest audit revision checks. A unique
(student_id,revision) is the final stale/concurrent guard. No separate revision,
student-account or theme preference table. Audit failure rolls back name/phone,
password, session and reset-grant changes together. Audit never stores passwords,
hashes/tokens/reset secrets. Only the dedicated isolated account may delete its
own disposable audit fixtures; main app audit grants are SELECT/INSERT only.

## Integration

Header/Dashboard/Owner request/tenant names read the existing users row. Authorized
Owner request/tenant details may read the Student's saved phone only after their
existing Boarding ownership query succeeds. No additional contact is shown when
phone is empty. Owner's own phone/bank settings remain on their existing model.
Account changes never rewrite original requests, tenancies, maintenance records,
issued bills, evidence, verified payments, receipts, agreed rates or dates.

Appearance uses the existing `smartboarding-theme` localStorage key and
`SmartBoardingTheme` API. Preview is temporary, Cancel restores saved preference,
and only the one-use server password-approved response persists a Settings save.
Header Sun/Moon remains an ordinary non-sensitive preference control. No migration
for duplicated theme state and no additional dependency.

## Activation and evidence

The Student sidebar exposes Settings only when `STUDENT_SETTINGS_ENABLED=1` after
separate 015 SQL/grant approval, verified backups and isolated tests. Disabled/direct
access fails safely rather than reading a missing schema. Do not rerun additive
SQL against an already migrated database. Keep additive history on rollback; no
DROP/reset/restore/destructive changes are authorized by ordinary activation.

Pure/mocked tests check values, role/gate binding, exact cards/forms. Real isolated
MySQL tests cover saved account data, identity/history integrity, live HTTP login/
gate/save, throttling, sessions/reset revocation, audit rollback and concurrency.
Shared Owner tests and Student-specific DOM models verify controller reuse. DOM
tests do not prove native visual layout, focus trapping or mobile rendering; report
browser checks separately and never insert fake production accounts for testing.
