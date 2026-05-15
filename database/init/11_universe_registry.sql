USE usstock;

CREATE TABLE IF NOT EXISTS symbols_registry (
    symbol VARCHAR(20) NOT NULL PRIMARY KEY,
    asset_type VARCHAR(20) NOT NULL DEFAULT 'EQUITY',
    sector VARCHAR(100) DEFAULT NULL,
    is_active TINYINT(1) NOT NULL DEFAULT 1,
    is_benchmark TINYINT(1) NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY idx_symbols_registry_active (is_active),
    KEY idx_symbols_registry_benchmark (is_benchmark)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

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
