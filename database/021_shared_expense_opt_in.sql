-- Other expenses remain Owner-only unless explicitly opted in after this migration.
USE smart_boarding_db;
ALTER TABLE expenses
    ADD COLUMN charge_to_tenants BOOLEAN NOT NULL DEFAULT FALSE,
    DROP CHECK chk_expense_utility_period,
    ADD CONSTRAINT chk_expense_sharing_flag CHECK (charge_to_tenants IN (0,1)),
    ADD CONSTRAINT chk_expense_utility_period CHECK (
        (category='other' AND charge_to_tenants=FALSE AND utility_period IS NULL) OR
        (category='other' AND charge_to_tenants=TRUE AND utility_period IS NOT NULL AND DAYOFMONTH(utility_period)=1) OR
        (category IN ('electricity','water') AND charge_to_tenants=FALSE AND utility_period IS NOT NULL AND DAYOFMONTH(utility_period)=1)
    );
