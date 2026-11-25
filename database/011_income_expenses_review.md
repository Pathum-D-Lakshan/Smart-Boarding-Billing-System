# Income & Expenses 011 — review before execution

Applied on 09 November 2026 (Asia/Colombo), after explicit approval
`APPROVE INCOME EXPENSES 011 SQL + GRANTS + TEST SQL`. The isolated DDL/grants and
20 finance integration tests passed before rollout. Full Python regression: 512
PASS; JavaScript behavioral checks: 122 PASS. Main writers were stopped, a fresh
verified SQL/file backup retained, and the main SQL/grants applied. All 23 original
table record digests remained unchanged; two empty finance tables and the precise
limited grants were verified. No fake main expenses or income were created.
Private manifest / rollout: `instance/finance_rollout_report.json`. Restore is not
rehearsed; do not blindly rerun CREATE. Further DDL/grants still require approval.

Complete SQL: `011_income_expenses.sql`,
`011_grant_income_expenses_app.sql`, `011_income_expenses_test.sql`.
Only two new tables: expenses + append-only expense_events. No existing table ALTER,
reset or deletion. Actual schema inspected: MySQL 8.4.7, 23 existing tables, no expenses.

Expenses have three editable fields (name <=150, positive DECIMAL(14,2), actual date),
Owner Boarding/creator FKs, timestamps, revision, request-key duplicate protection
and archived actor/time. Edits and archives require current Owner password, existing
failed-password throttle, current credential stamp, ownership, CSRF and row locks.
Audit records preserve old/new values and actor/time. No normal DELETE or Restore UI.

Income reads existing verified Bank Transfer and Cash payments only, by their UTC
decided_at translated to the Sri Lankan calendar month. This is the same decision/
collection reporting convention as Payments. Zero-balance settlements collect no
money; pending/rejected/unpaid bill values are excluded. No second income table.
Expense totals read active paid expenses by expense_date. Balance is Decimal income
minus expenses; negative results remain negative. Search filters records, not totals.

Monthly Bills utility inputs are not evidence that suppliers were paid. They are
never auto-imported into expenses. Owner enters actually paid utility/repair expenses
once. Future Maintenance/Reports reuse stable expense IDs and the finance service.

Main grants: SELECT/INSERT on two tables, seven necessary UPDATE columns on expenses.
No DELETE, audit UPDATE, global privileges, payment/billing mutation or new dependency.
Isolated test grants permit fixture SELECT/INSERT/UPDATE/DELETE only on these tables.

Rollout: consistent private schema/data/file backup and SHA-256 verification; source
checkpoint; apply isolated SQL/grants and test first. Stop verified main Flask writers,
take a fresh verified backup, apply main SQL/grants, compare all 23 original table
record digests and exact privileges, restart the main app on 5000. DDL auto-commits;
inspect partial failures rather than rerun blindly. Backup restore is not rehearsed.
Rollback disables finance writes while retaining records/audit. Any DROP/destructive
restore requires separate approval. Do not insert fake expenses/payments into main.
