-- Login activity audit table.
-- Development installs create this automatically when DB_AUTO_INIT=1.
-- Run this migration manually in production before deploying the feature.

CREATE TABLE IF NOT EXISTS login_logs (
    log_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    account_id INT NULL,
    account_code VARCHAR(50) NULL,
    account_role VARCHAR(30) NULL,
    event_type VARCHAR(20) NOT NULL,
    status VARCHAR(20) NOT NULL,
    ip_address VARCHAR(45) NULL,
    user_agent VARCHAR(512) NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_login_logs_account_created (account_id, created_at),
    INDEX idx_login_logs_created (created_at)
) ENGINE=InnoDB;
