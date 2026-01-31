-- Backtest Results Schema
-- Created: 2026-01-31

USE usstock;

-- Backtest runs table
CREATE TABLE IF NOT EXISTS backtest_runs (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    strategy_name VARCHAR(100) NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    total_return DECIMAL(12, 4),
    sharpe_ratio DECIMAL(10, 4),
    max_drawdown DECIMAL(10, 4),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    INDEX idx_strategy_name (strategy_name),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Equity curve table
CREATE TABLE IF NOT EXISTS equity_curve (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    run_id BIGINT NOT NULL,
    date DATE NOT NULL,
    equity_value DECIMAL(16, 4) NOT NULL,
    
    FOREIGN KEY (run_id) REFERENCES backtest_runs(id) ON DELETE CASCADE,
    UNIQUE KEY uk_run_date (run_id, date),
    INDEX idx_run_id (run_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Trade logs table
CREATE TABLE IF NOT EXISTS trade_logs (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    run_id BIGINT NOT NULL,
    symbol VARCHAR(10) NOT NULL,
    entry_date DATE,
    exit_date DATE,
    entry_price DECIMAL(12, 4),
    exit_price DECIMAL(12, 4),
    pnl DECIMAL(16, 4),
    
    FOREIGN KEY (run_id) REFERENCES backtest_runs(id) ON DELETE CASCADE,
    INDEX idx_run_id (run_id),
    INDEX idx_symbol (symbol)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;