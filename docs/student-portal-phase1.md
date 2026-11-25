# Student Portal Phase 1

Implemented in the existing main Flask app. No new database tables, privileges or
dependencies. Login still redirects Students to `/dashboard/student`; Owners keep
their existing landing page.

## Reused boundaries

- `student_requests.py` and `student_request_service.py`: published listings,
  cover authorization, Student requests/history and submission transactions.
- `tenancy_service.py`: approval and the same availability/effective-rate SQL.
  `rental_unit_queries` now supplies both scoped approval inventory and public
  discovery; unscoped private inventory queries are explicitly rejected.
- Existing Student Bills, Payments/receipts and Maintenance routes are linked.
- Existing Owner shell CSS/controller, SVG artwork, palette, typography, theme
  toggle and CSRF-protected Logout are reused on the Student shared layout.

## Dashboard

`student_portal_service.py` loads a read-only snapshot scoped to the authenticated
Student ID. New, Pending, Scheduled, Active and Previous states use actual request
and agreement records. Dates use Sri Lankan time and half-open `[start,end)`
periods. A checkout today is historical, even if the open row is still retained.
Future starts are Scheduled, never Active. Historical data remains accessible.
The existing lifecycle permits checkout on the start date (zero occupied nights);
this remains a valid scheduled agreement before that date, not a corrupt record.

Existing sequential agreements are allowed. Overlapping/invalid assignments,
conflicting pending requests or an approval without an agreement show a safe
review state instead of invented boarding data. The current agreement takes
precedence over an adjacent future stay; recent requests are shown separately.

View My Boarding links to the existing approved request's authorized agreement
details. Full My Boarding management and Student Settings are outside Phase 1,
and their sidebar entries honestly show Coming soon. No fake notifications,
review ratings, GPS distances, statistics, bills or Student profile records.

## Find Boarding

Existing `/student/boardings` supports server-side location/area, maximum budget,
Shared/Private type, all selected supported facilities and deterministic sorting.
Location matches name/address/city/district with parameterized literal LIKE text;
wildcards entered by the user are escaped. Budget uses positive Decimal money;
identifiers/sort expressions come from fixed code allowlists. Facilities reuse
Wi-Fi, Parking, Kitchen, Laundry, Study Area and CCTV only.

MySQL CTEs aggregate eligible registered Shared Beds and entire Private Rooms
before counting/pagination (12 boardings per page). There are two set-based search
queries, with no per-boarding inventory query. Shared prices come from saved
registered Bed rate history; future-bed defaults never become advertised rents.
Private physical beds are never separately counted as rental options. Cards label
the starting price's unit, and detail rent panels keep Shared/Private separate.

Only published boardings owned by active Owners appear; the schema currently has
no additional moderation status. Cover files use existing guarded routes and safe
fallbacks when no valid file exists. No bank/account/tenant identities are exposed.

Search checks availability from today for an open-ended stay. A future reservation
blocks a conflicting open-ended unit, so this is not a promise that all dates are
available. Details supports the existing intended-date check and grouped room
availability table. All-unavailable boardings can still be viewed without rent/type
filters, but cannot submit an invalid request. Search filters/pagination survive
detail/back navigation through allowlisted URL parameters only.

Request submission continues to use the existing one-pending-request constraint,
Student/Boarding locks, active/scheduled-tenancy rules and availability checks.
Owner approval remains the final authority for assignment, price and start date;
submission does not create a tenancy. No new independent request system exists.

## UI and later phases

Student sidebar order: Dashboard, Find Boarding, My Join Requests, My Boarding,
My Bills, My Payments, My Maintenance, Settings, Log out. Student collapse uses
only `student-sidebar-compact`; Owner preference remains independent. The existing
mobile drawer provides focus restoration, backdrop, Escape and background inert.
Both existing themes use the same shared storage and header toggle.

No full Student Bills/Payments/Maintenance redesign or Student Settings backend
was added. Existing pages automatically receive the shared Student shell.

## Verification

`test_student_portal.py`: pure date/state/filter validation and mocked main-app
dashboard/layout/privacy/error tests. `test_student_portal_mysql.py`: disposable
real MySQL fixtures, search prices/facilities/publication/reservations/pagination,
state transitions, scope and an actual HTTP Student -> Owner approval -> Student
workflow with the existing Flask app. Tests never seed main data or send email.
Existing Student submission/Owner approval/billing/payment/auth regressions remain
part of the full suite. Sidebar and theme JavaScript models do not prove native
layout, focus behavior or rendered theme quality; those need browser review.

Manual main check: Ctrl+F5, sign in with your registered Student -> Dashboard ->
Find Boarding -> search your Owner's actual published boarding -> View Details ->
choose intended date and Send Join Request -> verify Pending on Dashboard. In a
separate Owner session, approve and assign an available unit -> refresh Student
Dashboard/request details and confirm Scheduled/Active, unit, agreed rent and date.
Check Light/Dark, sidebar collapse and a mobile viewport. Use only authorized real
requests; do not create dummy production records. No guarantee of a real main
approval/browser pass is made unless explicitly recorded in the completion report.
