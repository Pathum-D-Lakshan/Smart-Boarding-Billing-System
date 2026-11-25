-- Reviewed additive billing integration. MySQL DDL auto-commits.
USE `smart_boarding_db`;
ALTER TABLE expenses
    ADD COLUMN category ENUM('electricity','water','other') NOT NULL DEFAULT 'other',
    ADD COLUMN utility_period DATE NULL,
    ADD COLUMN notes VARCHAR(500) NULL,
    DROP CHECK chk_expense_amount,
    ADD CONSTRAINT chk_expense_amount CHECK (amount >= 0 AND (category <> 'other' OR amount > 0)),
    ADD CONSTRAINT chk_expense_utility_period CHECK (
        (category='other' AND utility_period IS NULL) OR
        (category IN ('electricity','water') AND utility_period IS NOT NULL AND DAYOFMONTH(utility_period)=1)),
    ADD KEY idx_expense_utility (boarding_id,utility_period,category,archived_at);

ALTER TABLE billing_cycles
    ADD COLUMN utility_source ENUM('manual_legacy','expenses') NOT NULL DEFAULT 'manual_legacy',
    ADD COLUMN utility_expense_digest CHAR(64) NULL,
    ADD COLUMN utility_snapshot JSON NULL;

CREATE TABLE bill_email_deliveries (
    bill_id INT UNSIGNED NOT NULL,
    status ENUM('pending','sending','sent','failed','uncertain') NOT NULL DEFAULT 'pending',
    attempt_count INT UNSIGNED NOT NULL DEFAULT 0,
    claim_token CHAR(32) NULL,
    claimed_at DATETIME(6) NULL COMMENT 'UTC',
    last_attempt_at DATETIME(6) NULL COMMENT 'UTC',
    sent_at DATETIME(6) NULL COMMENT 'SMTP acceptance time, not inbox delivery',
    error_code VARCHAR(50) NULL,
    message_id VARCHAR(150) NOT NULL,
    created_at DATETIME(6) NOT NULL,
    PRIMARY KEY (bill_id),
    KEY idx_bill_mail_queue (status,created_at),
    CONSTRAINT fk_bill_mail_bill FOREIGN KEY (bill_id) REFERENCES monthly_bills (bill_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
