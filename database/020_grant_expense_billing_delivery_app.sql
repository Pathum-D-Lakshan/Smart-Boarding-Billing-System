GRANT UPDATE (category,utility_period,notes) ON smart_boarding_db.expenses TO 'smart_boarding_app'@'127.0.0.1';
GRANT UPDATE (utility_source,utility_expense_digest,utility_snapshot) ON smart_boarding_db.billing_cycles TO 'smart_boarding_app'@'127.0.0.1';
GRANT SELECT,INSERT ON smart_boarding_db.bill_email_deliveries TO 'smart_boarding_app'@'127.0.0.1';
GRANT UPDATE (status,attempt_count,claim_token,claimed_at,last_attempt_at,sent_at,error_code)
    ON smart_boarding_db.bill_email_deliveries TO 'smart_boarding_app'@'127.0.0.1';
