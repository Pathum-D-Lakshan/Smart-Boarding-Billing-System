-- REVIEW ONLY: execute after separate approval and a verified fresh backup.
-- Additive DDL auto-commits. Stop on any error; never reset existing tables.
USE `smart_boarding_db`;

CREATE TABLE `auth_sessions` (
    -- SHA-256 of a random 256-bit login token; the raw token is never stored here.
    `token_digest` BINARY(32) NOT NULL,
    `user_id` INT UNSIGNED NOT NULL,
    -- SHA-256 of the existing password stamp binds sessions to current credentials.
    `credential_stamp` BINARY(32) NOT NULL,
    `remember_me` BOOLEAN NOT NULL DEFAULT FALSE,
    `created_at` DATETIME(6) NOT NULL COMMENT 'UTC',
    `expires_at` DATETIME(6) NOT NULL COMMENT 'UTC',
    `revoked_at` DATETIME(6) DEFAULT NULL COMMENT 'UTC',
    PRIMARY KEY (`token_digest`),
    KEY `idx_auth_sessions_user_expiry` (`user_id`, `revoked_at`, `expires_at`),
    CONSTRAINT `fk_auth_sessions_user`
        FOREIGN KEY (`user_id`) REFERENCES `users` (`user_id`),
    CONSTRAINT `chk_auth_sessions_remember` CHECK (`remember_me` IN (0, 1)),
    CONSTRAINT `chk_auth_sessions_lifetime` CHECK (
        `expires_at` > `created_at`
        AND ((`remember_me` = FALSE AND `expires_at` <= TIMESTAMPADD(HOUR, 8, `created_at`))
          OR (`remember_me` = TRUE AND `expires_at` <= TIMESTAMPADD(DAY, 7, `created_at`)))
    ),
    CONSTRAINT `chk_auth_sessions_revocation`
        CHECK (`revoked_at` IS NULL OR `revoked_at` >= `created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
