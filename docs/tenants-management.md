# Owner Tenants Management

Entry point: `/owner/tenants`. Tenancies come exclusively from the existing approved
Join Request transaction; there is no Add Tenant or Delete action.

## Dates and summaries

Local agreement dates use Asia/Colombo. Intervals are start-inclusive and checkout-
exclusive. A NULL checkout is an open-ended agreement. Active means started and not
ended; Scheduled means starts in the future; Moved Out means an effective end has
been reached or an immediate checkout was confirmed. No scheduler is required.
These states describe the agreement, not proof of physical presence.
Moving Out Soon is an Active subset with checkout within 30 days, not another
occupant count. Summary cards are boarding-wide; filters/pagination apply to rows.

## Permitted operations

* Change a future scheduled start to another future date.
* Schedule or reschedule a future checkout.
* Cancel a future checkout only if an unbounded extension would not conflict.
* Confirm a completed checkout on/after start and no later than today.

Completed agreements are read-only. Every change requires a fresh current Owner
password, CSRF token and expected revision. Five failed confirmations per Owner
cause a 15-minute database-backed throttle. Inputs survive failures except the
password, which is never echoed/stored in the event log, cookie or localStorage.

## Transaction contract

Approval and lifecycle writers serialize Student -> Boarding -> Room parents.
Lifecycle changes then lock the target agreement and recheck Owner activation,
credential stamp, revision and overlapping Student/unit periods. A private hold
conflicts with every bed/room agreement in that room. Shared holds conflict with
the same bed or any private hold. Date changes and old/new-value audit events
commit together; any failure rolls both back. The approved 008 migration replaces
open-lifetime uniqueness with this period-aware contract; do not introduce another
tenancy writer without the same locks and overlap checks.

Room edits remain blocked by current or future reservations. Physical bed count is
separate from active agreements. Existing Student request pages can check a future
availability date; approval rechecks that date and saved rate under locks.

## Historical and financial boundaries

Original tenancy/source-request IDs, rental unit, agreed rent and source rate IDs
remain stable. The main app can update only the approved lifecycle columns and
append audit events; it cannot delete agreements or edit audit history.
Transfers and rent amendments are intentionally unavailable: they require a separate
assignment-history/amendment and billing-correction design. No bills, proration,
payments, settlements or fictional outstanding balances are generated here.
Future Billing/Payments/Maintenance must reference these same stable tenancy IDs,
respect historical effective dates and add their financial guards to the lifecycle
service. Room labels reflect current room records; original rental type comes from
the immutable agreement's rent unit.

## Verification

See `tests/README.md`. Mocked tests are distinct from opt-in isolated MySQL tests.
DOM models do not verify native modal focus trapping, pixel layout or mobile
rendering. Manually inspect Light/Dark, search/filter/pagination, Details, Review
Changes, masked password/eye, wrong-password retry, cancellation and successful
checkout on an authorized account in the main app. Never seed production fixtures.
