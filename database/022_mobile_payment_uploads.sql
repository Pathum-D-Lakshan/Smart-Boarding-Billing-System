-- Additive mobile proof capabilities and Owner notification outbox only.
USE smart_boarding_db;
CREATE TABLE payment_upload_links (
    link_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    token_digest BINARY(32) NOT NULL,
    student_id INT UNSIGNED NOT NULL,
    bill_id INT UNSIGNED NOT NULL,
    credential_stamp BINARY(32) NOT NULL,
    request_key CHAR(32) NOT NULL,
    created_at DATETIME(6) NOT NULL,
    expires_at DATETIME(6) NOT NULL,
    revoked_at DATETIME(6) NULL,
    used_at DATETIME(6) NULL,
    payment_id INT UNSIGNED NULL,
    active_bill_id INT UNSIGNED GENERATED ALWAYS AS (CASE WHEN revoked_at IS NULL AND used_at IS NULL THEN bill_id ELSE NULL END) STORED,
    UNIQUE KEY uq_mobile_link_digest(token_digest),
    UNIQUE KEY uq_mobile_link_request(request_key),
    UNIQUE KEY uq_mobile_link_active_bill(active_bill_id),
    KEY idx_mobile_link_student_time(student_id,created_at),
    CONSTRAINT fk_mobile_link_student FOREIGN KEY(student_id) REFERENCES users(user_id),
    CONSTRAINT fk_mobile_link_bill FOREIGN KEY(bill_id) REFERENCES monthly_bills(bill_id),
    CONSTRAINT fk_mobile_link_payment FOREIGN KEY(payment_id,bill_id) REFERENCES payments(payment_id,bill_id),
    CONSTRAINT chk_mobile_link_expiry CHECK(expires_at>created_at AND TIMESTAMPDIFF(SECOND,created_at,expires_at)<=1200),
    CONSTRAINT chk_mobile_link_use CHECK((used_at IS NULL AND payment_id IS NULL) OR (used_at IS NOT NULL AND payment_id IS NOT NULL))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE payment_notifications (
    payment_id INT UNSIGNED NOT NULL PRIMARY KEY,
    owner_id INT UNSIGNED NOT NULL,
    message_id VARCHAR(100) NOT NULL,
    status ENUM('pending','sending','sent','failed','uncertain') NOT NULL DEFAULT 'pending',
    attempt_count INT UNSIGNED NOT NULL DEFAULT 0,
    claim_token CHAR(32) NULL,
    error_code VARCHAR(50) NULL,
    created_at DATETIME(6) NOT NULL,
    claimed_at DATETIME(6) NULL,
    last_attempt_at DATETIME(6) NULL,
    sent_at DATETIME(6) NULL,
    UNIQUE KEY uq_payment_notification_message(message_id),
    KEY idx_payment_notification_queue(status,created_at),
    CONSTRAINT fk_payment_notification_payment FOREIGN KEY(payment_id) REFERENCES payments(payment_id),
    CONSTRAINT fk_payment_notification_owner FOREIGN KEY(owner_id) REFERENCES users(user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
