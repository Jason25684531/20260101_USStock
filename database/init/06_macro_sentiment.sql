-- ============================================
-- 06_macro_sentiment.sql
-- 宏觀經濟數據和市場情緒數據架構
-- 支持ML特徵工程和預測模型
-- ============================================

USE usstock;

-- 宏觀經濟數據表 (從FRED API獲取)
CREATE TABLE IF NOT EXISTS macro_data (
    id INT AUTO_INCREMENT PRIMARY KEY,
    date DATE NOT NULL COMMENT '數據日期',
    ticker VARCHAR(50) NOT NULL COMMENT 'FRED指標代碼（如UNRATE, GDP, DFF等）',
    value DECIMAL(20, 6) DEFAULT NULL COMMENT '指標數值',
    
    -- 時間戳
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    -- 索引
    UNIQUE KEY unique_date_ticker (date, ticker),
    INDEX idx_date (date),
    INDEX idx_ticker (ticker)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='宏觀經濟指標數據（FRED）';

-- 市場情緒數據表 (可選：用於未來的情緒分析擴展)
CREATE TABLE IF NOT EXISTS sentiment_data (
    id INT AUTO_INCREMENT PRIMARY KEY,
    date DATE NOT NULL COMMENT '情緒數據日期',
    keyword VARCHAR(100) NOT NULL COMMENT '關鍵詞或主題',
    score DECIMAL(5, 4) DEFAULT NULL COMMENT '情緒分數（-1到1之間，負為悲觀，正為樂觀）',
    source VARCHAR(50) DEFAULT 'twitter' COMMENT '數據來源（twitter, reddit, news等）',
    
    -- 時間戳
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    -- 索引
    UNIQUE KEY unique_date_keyword (date, keyword),
    INDEX idx_date (date),
    INDEX idx_keyword (keyword),
    INDEX idx_score (score)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='市場情緒數據';

-- 視圖：最近30天宏觀數據匯總（用於快速查詢）
CREATE OR REPLACE VIEW v_recent_macro AS
SELECT 
    ticker,
    date,
    value,
    LAG(value, 1) OVER (PARTITION BY ticker ORDER BY date) AS prev_value,
    ROUND(
        ((value - LAG(value, 1) OVER (PARTITION BY ticker ORDER BY date)) / 
        LAG(value, 1) OVER (PARTITION BY ticker ORDER BY date)) * 100, 
        2
    ) AS pct_change
FROM macro_data
WHERE date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
ORDER BY ticker, date DESC;

-- 視圖：常用宏觀指標樞紐表（將不同指標橫向展開）
CREATE OR REPLACE VIEW v_macro_pivot AS
SELECT 
    date,
    MAX(CASE WHEN ticker = 'UNRATE' THEN value END) AS unemployment_rate,
    MAX(CASE WHEN ticker = 'GDP' THEN value END) AS gdp,
    MAX(CASE WHEN ticker = 'DFF' THEN value END) AS fed_funds_rate,
    MAX(CASE WHEN ticker = 'CPIAUCSL' THEN value END) AS cpi,
    MAX(CASE WHEN ticker = 'VIXCLS' THEN value END) AS vix
FROM macro_data
WHERE ticker IN ('UNRATE', 'GDP', 'DFF', 'CPIAUCSL', 'VIXCLS')
GROUP BY date
ORDER BY date DESC;
