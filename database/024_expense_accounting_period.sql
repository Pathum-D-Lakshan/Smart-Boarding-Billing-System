USE smart_boarding_db;

ALTER TABLE expenses
    ADD COLUMN accounting_period DATE NULL DEFAULT NULL
        COMMENT 'First day of the selected accounting month; NULL uses the paid date month',
    ADD CONSTRAINT chk_expense_accounting_period CHECK (
        accounting_period IS NULL OR
        (accounting_period BETWEEN '2000-01-01' AND '2100-12-01' AND DAYOFMONTH(accounting_period)=1)
    ),
    ADD INDEX idx_expense_accounting_period (boarding_id, archived_at, accounting_period);
