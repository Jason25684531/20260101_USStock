-- ============================================
-- 09_news_cache.sql
-- Company news cache for Phase 3 sentiment pipeline
-- ============================================

USE usstock;

CREATE TABLE IF NOT EXISTS news_cache (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    symbol VARCHAR(16) NOT NULL COMMENT '股票代碼',
    date DATETIME NOT NULL COMMENT '新聞發布時間',
    title VARCHAR(512) NOT NULL COMMENT '新聞標題',
    summary TEXT NULL COMMENT '新聞摘要或內文截斷',
    url VARCHAR(1024) NULL COMMENT '新聞連結',
    provider VARCHAR(64) DEFAULT 'yfinance' COMMENT 'OpenBB provider',
    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '寫入快取時間',

    INDEX idx_news_symbol_date (symbol, date DESC),
    INDEX idx_news_date (date),
    INDEX idx_news_provider (provider)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='公司新聞快取';