# Student My Maintenance

`student_maintenance` remains registered on the existing main Flask application.
The Student workspace uses `templates/student/base.html`, existing navigation,
SVG icons, typography/theme tokens and the shared native maintenance dialog.
No Student Dashboard redesign or second Owner lifecycle exists.

GET `/student/maintenance` shows only the signed-in Student's own history, three
compact cards (Total/In Progress/Resolved), a real Pending badge on My Requests,
reference/title search, status/sort and 15-row pagination. My Requests includes
all own requests; Request History is a server-filtered resolved-request view.
Summary counts always cover the Student's own full history regardless of filters.
The Report a New Issue button opens the form on click, never automatically on
the overview. Ineligible Students can inspect a disabled form preview; they cannot
submit. Actual reporting requires a current approved, open tenancy that has
started and whose exclusive end date has not passed. Identity/Boarding/Room are
derived again on POST, under the existing Student -> Boarding -> Room -> Tenancy locks.

GET/POST `/student/maintenance/create` reuse the existing authoritative insert.
The Student-only form has an accessible native photo picker/drop zone, inline
file-size/type feedback and a separate presentation controller. No file uploads
automatically when chosen/dropped. Browser validation does not replace decoding
or tenancy checks on the server. Report/View retain the shared centered dialog.
Title is 1–150 characters and description 1–1000, matching the existing schema.
Location is assigned Room or Common Area; priority uses the existing allowlist.
Status starts as Pending; forged IDs/status fields cannot select another tenancy.
One UUID form key prevents duplicate-click records. Similar titles are allowed
with fresh keys. A locked Student row serializes a 20-new-reports/minute limit;
saved idempotent retries bypass that quota. Clear 429 errors preserve form text.

GET `/student/maintenance/<id>` displays original location snapshots, public Owner
updates and only real submitted/started/resolved timestamps. Owner Update was
already explicitly marked Student-visible in the Owner form. Owner expense/audit
details remain private. The Student has no edit/delete/status mutation routes.
Existing Owner Start/Resolve rules, password confirmation and audit remain intact,
including the existing direct resolution option (no invented Started timestamp).
Status is read fresh when viewing/refreshing; no push notification is claimed.

## Approved optional photo

014 adds only `maintenance_photos`, one immutable photo per request. Activation
requires the separately approved SQL/grants and `MAINTENANCE_PHOTOS_ENABLED=1`.
Without activation, core text workflows work and no upload control is offered.
The installed Pillow is reused; no added dependency. One JPG/JPEG/PNG up to 5 MiB
is verified by extension, signature, full decode, dimension and animation checks.
Images are at most 20 megapixels/10,000px per side; resized within 1920px, stripped
of EXIF/GPS and normalized on a fresh RGB canvas into private WebP.

Generated filenames live under `instance/maintenance-photos`, never static. The
database retains normalized-byte hash/dimensions/size. Request/photo/event save
atomically. Failed transactions delete only provably unreferenced generated files;
uncertain COMMIT outcomes keep referenced evidence. File write errors preserve
text safely; file inputs must be reselected after validation errors.

GET `/student/maintenance/<id>/photo` and `/owner/maintenance/<id>/photo` enforce
the same reporter/Boarding ownership before reading generated paths. Guests and
other Students/Owners cannot view them. Retrieval rechecks stored length/hash and
sets private no-store, nosniff, sandbox CSP and same-origin resource policy. `?download=1`
downloads normalized evidence without revealing an original filename or disk path.
No PDF, image editing/deletion, public sharing or category schema is added.

No tenancy, Room/Bed availability, rent, expense, bill, payment or receipt changes
occur from reporting/resolving. Owner expense links remain separate and private.
CSRF/session/role checks and parameterized SQL remain mandatory on direct requests.

## Verification boundaries

Real isolated MySQL tests cover eligibility, scope, identity, paging/search,
idempotency/throttle, actual Owner -> Student progress, rollback/concurrency,
Shared/Private/Common locations and secure optional photo access/storage failures.
Existing real HTTP integration uses this same Flask app with isolated fixtures.
DOM models cover the native dialog controller; these do not prove browser layout,
focus trapping or mobile rendering. Main writes require a legitimate active tenant;
do not manufacture main records to bypass that eligibility.
