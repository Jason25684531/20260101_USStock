USE usstock;

CREATE TABLE IF NOT EXISTS swing_ranking_performance (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    recommendation_date DATE NOT NULL,
    symbol VARCHAR(10) NOT NULL,
    rank_position INT NULL,
    score DECIMAL(8, 4) NULL,
    setup_type VARCHAR(64) NULL,
    provider_health_status VARCHAR(32) NOT NULL DEFAULT 'unknown',
    recommendation_source VARCHAR(32) NOT NULL DEFAULT 'unknown',
    entry_close DECIMAL(12, 4) NULL,
    close_5d DECIMAL(12, 4) NULL,
    close_10d DECIMAL(12, 4) NULL,
    close_20d DECIMAL(12, 4) NULL,
    forward_return_5d DECIMAL(12, 6) NULL,
    forward_return_10d DECIMAL(12, 6) NULL,
    forward_return_20d DECIMAL(12, 6) NULL,
    hit_5d TINYINT(1) NULL,
    hit_10d TINYINT(1) NULL,
    hit_20d TINYINT(1) NULL,
    max_drawdown_20d DECIMAL(12, 6) NULL,
    max_favorable_excursion_20d DECIMAL(12, 6) NULL,
    evaluation_status VARCHAR(32) NOT NULL DEFAULT 'unknown',
    risk_flags_json JSON NULL,
    reasons_json JSON NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    UNIQUE KEY uk_swing_perf_recommendation (recommendation_date, symbol),
    INDEX idx_swing_perf_date (recommendation_date),
    INDEX idx_swing_perf_setup (setup_type),
    INDEX idx_swing_perf_provider (provider_health_status, recommendation_source)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
