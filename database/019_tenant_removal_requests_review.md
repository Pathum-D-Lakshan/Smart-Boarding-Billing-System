# Owner → Admin tenant removal requests 019 — approved and applied

Approval: `APPROVE TENANT REMOVAL 019 SQL + GRANTS + TEST SQL`, 14 November 2026.
Isolated rollout/tests preceded main rollout. Main backup:
`instance/backups/before_tenant_removal_20261114T074209Z_6a9d5d.sql` (UTC filename).
Hashes verified; no restore rehearsal. All 34 original-table column/value digests remained unchanged.
Main now has 36 tables. Exact new table/column grants verified; main DELETE not granted.
TENANT_REMOVAL_REQUESTS_ENABLED=1 enabled after tests and main app restarted on port 5000.
No production request, decision, account creation or real tenant checkout was executed for testing.

Correction requested by user: an Owner sends a removal request to Admin; submitting it must not
immediately end the tenant's stay. Admin reviews and approves/rejects. This is separate from user
account suspension/reactivation. Ordinary existing tenancy scheduling/check-out remains available;
the newly introduced direct End Stay / Remove Tenant action is replaced by Request Tenant Removal.

SQL: `019_tenant_removal_requests.sql`, `019_grant_tenant_removal_requests_app.sql`,
`019_tenant_removal_requests_test.sql`. Two new request/audit tables only, no existing table ALTER,
reset/delete, new dependency or promotion of accounts. Request records link to existing tenancy,
Owner, Student and Boarding. UNIQUE generated pending-tenancy key blocks concurrent duplicate Pending
requests. Rejected history is retained and a new request may be submitted. Audit is append-only.
Main rights are SELECT/INSERT plus UPDATE of six decision columns; audit SELECT/INSERT only.
Isolated table DELETE is fixture cleanup only. Existing lifecycle grants perform approved checkout.

Owner: shared existing Tenant modal, actual balance, required reason, explicit financial acknowledgement,
current password + CSRF. Identity/boarding/Student come from the scoped tenancy. Request+audit commit
together; tenancy is unchanged while Pending. Status/reason/history stay visible in Tenant Details.

Admin: Manage Users → Tenant Removal Requests, Pending count/dashboard link, search/status/pagination,
centered review and fresh password/CSRF. Only request-specific identity/assignment and aggregate issued
bill totals (no bank details/slips/invoice contents/financial browsing) are exposed, with Owner consent.
Submission and current totals are distinct; financial changes require fresh review. Approval locks
Student/Boarding/Room/Tenancy/Owner/current request, verifies unchanged agreement/ownership, and commits
today's checkout + lifecycle audit + request decision + request audit atomically. Rejection changes
only request/audit. Outstanding debt never disappears and does not block approved checkout. No final
bill/proration/refund is automatic. Admin account suspension is not part of this flow.

Rollout: backup hash verification (restore rehearsal not claimed), approved isolated SQL/grants/tests,
fresh main backup during short maintenance, main SQL/grants and original-column row digest comparison.
TENANT_REMOVAL_REQUESTS_ENABLED=1 only after applied schema/test evidence. DDL auto-commits; stop on
partial/already-applied schema. Do not fake requests or end a real tenant's stay for testing.
Rollback keeps additive history; feature disable may hide new requests but must never enable direct
Owner removal as a fallback. Restore/drop or other destructive recovery needs separate approval.
