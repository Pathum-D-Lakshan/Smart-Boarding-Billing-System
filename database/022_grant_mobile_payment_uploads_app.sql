GRANT SELECT,INSERT ON smart_boarding_db.payment_upload_links TO 'smart_boarding_app'@'127.0.0.1';
GRANT UPDATE(revoked_at,used_at,payment_id) ON smart_boarding_db.payment_upload_links TO 'smart_boarding_app'@'127.0.0.1';
GRANT SELECT,INSERT ON smart_boarding_db.payment_notifications TO 'smart_boarding_app'@'127.0.0.1';
GRANT UPDATE(status,attempt_count,claim_token,error_code,claimed_at,last_attempt_at,sent_at) ON smart_boarding_db.payment_notifications TO 'smart_boarding_app'@'127.0.0.1';
