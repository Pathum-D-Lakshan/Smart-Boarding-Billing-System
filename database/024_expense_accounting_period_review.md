# Expense accounting allocation

`expense_date` remains the actual paid date. The nullable `accounting_period`
stores the first day of the month selected by the Owner. Existing rows keep
`NULL` and remain grouped by their original paid date. No backfill is required.
The existing `utility_period` stays independent for utility and shared-expense
billing. Reports use the same accounting expense scope as Income & Expenses.

The complete main SQL is in `024_expense_accounting_period.sql`. It adds one
column, its validation check and one index. The separate grant permits updates
to that column only. The isolated migration uses the same DDL and retains the
existing isolated test user's table permissions. No bill, payment, receipt,
tenancy or expense is deleted or recalculated by the migration.

Before applying, take a transaction-consistent backup of the affected schemas
and verify the backup completed and is readable. Apply the isolated SQL first
and verify calendar allocation, edit/archive, and issued invoice protection.
Apply main SQL and its grant during a short maintenance window because the
`ALTER TABLE` may wait on a metadata lock. Verify the column and exercise the
runtime permissions before reloading the main application.

The nullable column is compatible with the old application. If deployment must
be rolled back after use, retain the column to preserve allocation data. The
old application groups expenses by paid date while it is in service, so pause
accounting operations until the allocation-aware version is restored.
