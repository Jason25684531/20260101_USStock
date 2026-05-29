USE usstock;

CREATE TABLE IF NOT EXISTS swing_calibration_audit_log (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    event_type VARCHAR(32) NOT NULL,
    profile_version VARCHAR(128) NULL,
    previous_profile_version VARCHAR(128) NULL,
    profile_path TEXT NULL,
    created_from_sample_size INT NULL,
    score_bucket_status VARCHAR(32) NULL,
    top_rank_status VARCHAR(32) NULL,
    risk_flag_status VARCHAR(32) NULL,
    drift_status VARCHAR(32) NULL,
    event_payload_json JSON NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    INDEX idx_swing_calib_audit_created_at (created_at),
    INDEX idx_swing_calib_audit_event_type (event_type),
    INDEX idx_swing_calib_audit_profile_version (profile_version)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
