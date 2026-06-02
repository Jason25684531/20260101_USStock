USE usstock;

CREATE TABLE IF NOT EXISTS symbols_registry (
    symbol VARCHAR(20) NOT NULL PRIMARY KEY,
    asset_type VARCHAR(20) NOT NULL DEFAULT 'EQUITY',
    sector VARCHAR(100) DEFAULT NULL,
    is_active TINYINT(1) NOT NULL DEFAULT 1,
    is_benchmark TINYINT(1) NOT NULL DEFAULT 0,
    whale_held_pct DECIMAL(10, 4) DEFAULT NULL COMMENT 'Top holder / whale ownership concentration percentage',
    inst_count INT DEFAULT NULL COMMENT 'Institutional holder count',
    institutional_net_buy DECIMAL(18, 4) DEFAULT NULL COMMENT 'Latest institutional net buying or average percentage change signal',
    sentiment_score DECIMAL(8, 4) DEFAULT NULL COMMENT 'Latest 24H news sentiment score bounded from -1 to 1',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY idx_symbols_registry_active (is_active),
    KEY idx_symbols_registry_benchmark (is_benchmark),
    KEY idx_symbols_registry_sentiment (sentiment_score),
    KEY idx_symbols_registry_inst_count (inst_count)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

ALTER TABLE symbols_registry
    ADD COLUMN IF NOT EXISTS whale_held_pct DECIMAL(10, 4) DEFAULT NULL COMMENT 'Top holder / whale ownership concentration percentage',
    ADD COLUMN IF NOT EXISTS inst_count INT DEFAULT NULL COMMENT 'Institutional holder count',
    ADD COLUMN IF NOT EXISTS institutional_net_buy DECIMAL(18, 4) DEFAULT NULL COMMENT 'Latest institutional net buying or average percentage change signal',
    ADD COLUMN IF NOT EXISTS sentiment_score DECIMAL(8, 4) DEFAULT NULL COMMENT 'Latest 24H news sentiment score bounded from -1 to 1';

CREATE TABLE IF NOT EXISTS universe_memberships (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    universe_code VARCHAR(50) NOT NULL,
    membership_type VARCHAR(20) NOT NULL DEFAULT 'index',
    is_active TINYINT(1) NOT NULL DEFAULT 1,
    first_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_universe_membership (symbol, universe_code, membership_type),
    KEY idx_universe_memberships_universe (universe_code, is_active),
    CONSTRAINT fk_universe_memberships_symbol
        FOREIGN KEY (symbol) REFERENCES symbols_registry(symbol)
        ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS universe_sync_runs (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    universe_code VARCHAR(50) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'queued',
    total_symbols INT NOT NULL DEFAULT 0,
    processed_symbols INT NOT NULL DEFAULT 0,
    started_at TIMESTAMP NULL DEFAULT NULL,
    finished_at TIMESTAMP NULL DEFAULT NULL,
    error_message TEXT DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY idx_universe_sync_runs_code (universe_code, created_at),
    KEY idx_universe_sync_runs_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
