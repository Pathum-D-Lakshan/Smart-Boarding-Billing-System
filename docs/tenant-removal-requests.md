# Owner-requested tenant removal with Admin approval

Owner entry point: Join Requests → approved request View → Request Tenant Removal — Send to Admin,
or Tenants → Request Removal (a separate button beside Manage Tenancy, for Active and Scheduled rows).
The existing centered Tenant dialog displays actual issued-bill
amounts, requires a 1–500 character reason, explicit payment review/request-specific aggregate sharing
consent and current Owner password. Submit sends the request and audit only: Active/Scheduled status remains unchanged.
Pending, rejected and approved request history is visible to the Owner, including after checkout.
The list shows Request Sent (disabled) while Pending, including after refresh/re-login. The existing
response replaces the visible row immediately after submission. Rejection enables Request Again.
Approved ended agreements show Removed — Admin approved / History only in All Statuses; they are
absent from Active/Scheduled assignments and their units are released. History and debt are retained.
Refresh Status or opening View Details re-reads decisions made in another Admin session.
One Pending request per tenancy is enforced under locks and by MySQL UNIQUE. Rejection permits another
request while retaining previous records. The public direct `end_stay` Owner action is rejected.
Existing voluntary move-out/scheduling remains a distinct preserved operational workflow.

Admin entry point: Dashboard → Tenant Removal Requests, or Manage Users → Tenant Removal Requests.
This extends the existing Manage Users section; the Admin Sidebar is unchanged. List/search/status/
pagination and the existing centered details/password-eye controller are reused. Admin sees only the
request's identity/assignment, Owner reason, submission totals and current aggregate totals. Invoice
contents, bank details, slips and other private financial browsing are not added. Decision notes are
visible to the requesting Owner. Only the request-specific consented aggregate projection is shared.

Approval requires Admin role, a current normal server session, password re-verification, CSRF,
confirmation and current balance acknowledgement. The transaction locks Admin → Student → Boarding →
Room → Tenancy → Owner → Request, revalidates ownership/current agreement revision, and compares the
financial review fingerprint. Stale assignments/financial views or duplicate decisions are rejected.
The request, lifecycle checkout event and removal audit commit atomically. Rejection changes only the
request/audit; audit failures roll back the whole operation.

Approved active checkout uses Sri Lanka's current date. For a Scheduled reservation Admin approval
cancels it before move-in: status becomes ended and end_date equals the preserved future start_date,
representing zero occupied nights. The reserved unit is released; no real start date is backdated.
Both paths preserve agreed rent, original Approved Join Request,
Student account and all bills/payments/receipts. It releases only this approved tenancy's Shared Bed or
entire Private Room assignment. Pending slips are not treated as paid. Unpaid balances remain payable;
there is no automatic debt waiver, final bill, proration or refund. Existing frozen billing snapshots
stay intact and later assignment/billing-cohort guards still apply.

Schema/grants: separately approved 019 adds `tenant_removal_requests` and append-only
`tenant_removal_events`. No existing table/records are reset or altered by DDL. Main has SELECT/INSERT
and six request decision columns UPDATE; audit SELECT/INSERT only. Test DELETE is isolated cleanup.
TENANT_REMOVAL_REQUESTS_ENABLED=1 only after isolated tests and verified main rollout. Feature-off never
reenables the mistaken direct Owner removal action. Backup restore/drop needs separate approval.

Automated tests use disposable isolated fixtures and current Flask routes. No real Owner request,
Admin decision or tenant checkout is created for testing on the main system. Native browser visual
validation is reported separately from HTTP/template/MySQL/JS harness evidence.
