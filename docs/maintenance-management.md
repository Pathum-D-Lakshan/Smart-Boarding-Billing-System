# Maintenance Management - Student requests, Owner progress

Current policy (09 November 2026, Asia/Colombo) supersedes the original 012
implementation: only an authenticated Student with a current approved active
tenancy can submit maintenance. The Owner reviews and manages progress only.

## Workflow

Student Report an Issue -> Pending -> Owner View -> Mark as In Progress ->
Mark as Resolved. Pending is the automatic initial submission status. In Progress
means the Owner has started arranging/carrying out the repair. Direct Pending ->
Resolved remains permitted if the repair is already complete, with the same
password, required resolution note and confirmation. Resolved is final.

The Owner cannot create maintenance requests, edit Student title/description/
priority/location, or add/change expense links. These restrictions apply to real
routes and direct service callers, not only hidden buttons. Retired Owner Create
GET/POST returns 403 after authentication; retired Edit actions return 404.
Historical Owner-created records and existing expense links remain readable and
unchanged. Legacy Owner reports are read-only, including direct status POSTs.

Owner `/owner/maintenance`: four real summary counts, title/reporter search,
status filter, sorting, pagination, View and eligible progress actions. Students
use the existing minimal `/student/maintenance` pages, Report an Issue, own history
and saved Owner updates/resolution. No new Student Dashboard architecture.

## Authorization, history and transactions

Only one current approved open tenancy qualifies: start <= Sri Lankan today and
checkout > today or absent. Scheduled/ended tenants cannot create new reports.
Student identity, Boarding, tenancy and assigned Room derive from trusted current
records; only assigned Room or Common Area is selectable. Historical own reports
remain readable after checkout. Neither another Owner nor another Student can
read or update unrelated reports.

Student title/description/priority/location, reporter, Boarding, tenancy and name/
location snapshots are preserved. Owner Start Work can add a visible progress
note. Resolve requires the current Owner password, existing shared 5-failure /
15-minute throttle, a meaningful resolution note and explicit confirmation. Wrong
or blank passwords preserve the note and reopen an empty editable password field;
Show/Hide is an accessible non-submit button. Original resolution facts cannot
be changed. There is no reopen, delete or archive action.

All writes require active account/role, Owner scope, CSRF, parameterized SQL,
server validation and revision checks. Student -> Boarding -> Room -> Tenancy
locks match checkout/approval and dates are rechecked after waiting. Owner status
updates lock Boarding -> Owner -> Request and verify the credential stamp for
resolution. An audit event and status update commit together or roll back.
Idempotent Student create keys, duplicate-resolution rejection and stale-revision
conflicts prevent duplicate/lost writes. GET requests do not mutate data.

## Finance, themes and future integration

Maintenance does not alter rent, availability, assignments, bills, payments,
receipts or expenses. Repair costs are recorded separately in Income & Expenses.
Previously linked expenses remain Owner-only, including an archived-history label;
Students never receive private expense metadata or audit data. New link editing
is unavailable under the Owner progress-only policy.

Dark Navy/Cyan and Sky Blue Light themes, readable shared typography, SVG icons,
shared Owner Sidebar/header and existing Student navigation are preserved. View,
Start Work and Resolve use one centered native dialog with safe scrolling,
Escape/focus restoration and ordinary HTML page/form fallbacks. Critical native
POSTs block duplicate submissions; passwords clear on close/mode/navigation.

Existing owner-scoped `load_requests`, `load_request`, `maintenance_summary` and
`current_tenancy` services remain reusable by future Reports/Student Dashboard.
No second request/tenancy model or additional feature was created.

## Database and verification

The already-approved/applied 012 tables and grants are unchanged by this policy
correction. No migration, new grants, dependency or data cleanup is required.
Legacy rows/audit remain intact. Original DDL/grant rollout evidence remains in
`database/012_maintenance_review.md` and ignored `instance/` reports/backups.

`test_maintenance_validation.py`: pure server validation and pre-SQL action gates.
`test_maintenance_mysql.py`: real isolated Student submissions, Owner rejection of
Create/Edit, Start/Resolve, role/CSRF/ownership, wrong-password retry, snapshots,
legacy read-only history/expense privacy, rollback, concurrent create/status/
checkout, filters and same-Flask-app HTTP Student -> Owner -> Student workflow.
Fixtures use only the approved isolated database and clean up their own IDs.
`test_maintenance.js` models the native dialog/eye/POST/retry/fallback behavior;
it does not prove native browser visual layout or focus trapping.

Manual check on main 5000: Ctrl+F5 -> Owner Maintenance (no Add/Edit) -> View a
real Student request -> In Progress -> Resolved with note/current password ->
refresh and Student My Maintenance. For an empty list, an authorized actual active
Student must submit a genuine issue first. Do not seed fake production requests.
