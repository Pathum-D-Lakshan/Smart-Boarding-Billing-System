# Student My Boarding

Read-only implementation on the existing `/student` blueprint, using the existing
authentication/session/role checks and a single MySQL read-only snapshot.
No migrations, privilege changes or dependencies are required.

## Routes and UI

- `GET /student/my-boarding`: own effective agreement by default; optional
  allowlisted `tab`, unsigned `tenancy_id` and validated `history_page`.
- `GET /student/my-boarding/<tenancy_id>/cover`: own approved agreement and current
  published/active Owner profile only. No filename/path exposed; no-store headers.

My Boarding is active in the shared Student sidebar; Student Settings remains
Coming soon. Dashboard View My Boarding and previous-agreement links open the
same page. Owner pages and their data writes are unchanged.

Boarding overview uses an actual saved cover or fallback, current published
description/address/contact phone/contact email and the authorized contact name.
Tabs are native GET navigation: Overview, Room & Rent, Facilities, Tenancy.
Only the selected section is rendered. Links support keyboard Tab/Enter, browser
Back, opening a tab in a new browser tab and JavaScript-disabled operation, without
pretending to implement ARIA widget arrow-key behavior. Focus styles are retained.

## Authoritative state and data

`student_portal_service.load_dashboard_snapshot` is shared with the Dashboard.
It resolves New, Pending, Scheduled, Active and Previous states from the same
Student-owned agreements and requests. My Boarding status labels use the existing
Owner `tenancy_lifecycle.phase` function, Sri Lankan dates and `[start,end)` stays.
Checkout today is historical. The existing policy permitting checkout on the start
date remains valid; an agreed future start stays Scheduled, never prematurely Active.

`student_boarding_service` projects only authorized contract/profile fields from
users, boardings, rooms, beds, join_requests and tenancies. Assigned Room/Bed,
rent unit, agreed monthly rent and effective start/end dates come from the tenancy.
Approval date/reference come from its approved source request. Agreed rent never
comes from today's Room/Bed price or a new-bed default. No transfer/amendment model
exists in the inspected schema, so none is invented. Floor uses the existing
formatter, preserving zero as Ground Floor. Room-specific facilities are not stored
separately; the Facilities tab uses the saved Boarding Profile allowlist.

Current agreement is preferred, then earliest valid future agreement, then the
latest historical agreement when no pending request takes precedence. Own agreement
history is paginated ten per page. Older or additional future records can be
selected with ownership-checked IDs. Invalid/overlapping relationships show a safe
review state; a pending request never becomes an approved residence.

## Privacy and publication

Every selected/cover query includes the authenticated Student ID. Browser identity,
room, rent and status values have no write effect. No write endpoint is introduced.
No other tenant identities, account email/password/hash/session data, bank details,
storage filename, rate IDs or audit payloads reach the page.

Unpublished or inactive-Owner profile fields (photo, mutable description, address,
contacts, Owner name and facilities) are hidden. The student's own agreement identity,
assigned unit, agreed rent/dates and request remain readable even after unpublishing
or move-out. Current published profile information is not represented as an immutable
historical profile snapshot. Existing historical Bills/Payments/receipts remain scoped
by their own modules; My Boarding does not generate bills or create payments.

## Quick actions

Existing My Bills, My Payments and own Join Request links are reused. No direct
payment submission is offered without an issued bill. Report an Issue opens the
existing Student Maintenance create route only for the selected current Active
agreement. Scheduled/historical/review states show an unavailable explanation.
The Maintenance backend rechecks active occupancy on its own request, so stale
pages do not grant permission. No leave/edit/delete workflow is added.

## Verification boundaries

`test_student_my_boarding.py` covers mocked routes, safe projection/inputs, all
four selected-only native tabs, authorization, empty/pending/review and Quick Actions.
`test_student_my_boarding_mysql.py` uses disposable accounts on the previously
approved isolated database for real approval, Shared/Private assignments, lifecycle
rescheduling/checkout, agreed rent retention, history, profile/cover privacy and
read-only behavior. The existing actual HTTP Student -> Owner approval -> Student
test now opens all four My Boarding sections as well. It runs the same Flask app,
not a separately implemented demo or production fixtures.

Automated markup/DOM/HTTP tests do not prove native browser visual layout, focus,
mobile rendering or theme appearance. Record those separately. No email is sent.

Main manual check: Student Login -> My Boarding -> verify actual Scheduled/Active
status and unit/rent/date -> open all four tabs -> check My Bills/Payments/request
links. Use Owner at 127.0.0.1 and Student at localhost for independent browser tabs.
After an authorized Owner lifecycle change, refresh Student My Boarding and Dashboard;
both must reflect the same saved change. Do not edit real agreements merely to stage
a test, and do not create fake production tenants. Review mobile/sidebar/Light/Dark.
