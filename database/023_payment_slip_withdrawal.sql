-- Apply to the explicitly selected test or main schema only after approval.
-- Existing record values and runtime privileges stay intact.
ALTER TABLE payment_events
    MODIFY COLUMN event_type ENUM('submitted','verified','rejected','cash_recorded','zero_settled','withdrawn') NOT NULL;

ALTER TABLE payments
    MODIFY COLUMN status ENUM('submitted','verified','rejected','withdrawn') NOT NULL,
    DROP CHECK chk_payment_decision,
    ADD CONSTRAINT chk_payment_decision CHECK (
        (status='submitted' AND method='bank_transfer' AND decided_by IS NULL AND decided_at IS NULL AND rejection_reason IS NULL)
        OR (status='verified' AND decided_by IS NOT NULL AND decided_at IS NOT NULL AND rejection_reason IS NULL)
        OR (status='rejected' AND method='bank_transfer' AND decided_by IS NOT NULL AND decided_at IS NOT NULL
            AND rejection_reason IS NOT NULL AND CHAR_LENGTH(TRIM(rejection_reason))>0)
        OR (status='withdrawn' AND method='bank_transfer' AND decided_by IS NOT NULL AND decided_by=submitted_by
            AND decided_at IS NOT NULL AND rejection_reason IS NULL)
    );
