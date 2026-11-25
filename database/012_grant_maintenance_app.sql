GRANT SELECT, INSERT ON `smart_boarding_db`.`maintenance_requests` TO 'smart_boarding_app'@'127.0.0.1';
GRANT UPDATE (`issue_title`,`description`,`priority`,`room_id`,`room_label`,`owner_note`,`resolution_note`,
    `expense_id`,`status`,`revision`,`updated_at`,`status_changed_at`,`status_changed_by`,
    `started_at`,`started_by`,`resolved_at`,`resolved_by`)
    ON `smart_boarding_db`.`maintenance_requests` TO 'smart_boarding_app'@'127.0.0.1';
GRANT SELECT, INSERT ON `smart_boarding_db`.`maintenance_events` TO 'smart_boarding_app'@'127.0.0.1';
