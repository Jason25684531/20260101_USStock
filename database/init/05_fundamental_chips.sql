-- ============================================
-- 05_fundamental_chips.sql
-- 擴展數據庫以支持基本面和機構持股（Chips）數據
-- ============================================

USE usstock;

-- 創建基本面數據表
CREATE TABLE IF NOT EXISTS stock_fundamentals (
    id INT AUTO_INCREMENT PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    data_date DATE NOT NULL,
    
    -- 估值指標
    pe_ratio DECIMAL(10, 2) DEFAULT NULL COMMENT '市盈率 (P/E Ratio)',
    peg_ratio DECIMAL(10, 2) DEFAULT NULL COMMENT 'PEG比率 (Price/Earnings to Growth)',
    pb_ratio DECIMAL(10, 2) DEFAULT NULL COMMENT '市淨率 (P/B Ratio)',
    
    -- 成長指標
    revenue_growth_yoy DECIMAL(10, 4) DEFAULT NULL COMMENT '年度營收增長率 (YoY %)',
    earnings_growth_yoy DECIMAL(10, 4) DEFAULT NULL COMMENT '年度盈利增長率 (YoY %)',
    
    -- 機構持股（Chips - Smart Money）
    inst_ownership_pct DECIMAL(10, 4) DEFAULT NULL COMMENT '機構持股百分比 (%)',
    inst_holders_count INT DEFAULT NULL COMMENT '機構持有者數量',
    
    -- 其他財務指標
    market_cap BIGINT DEFAULT NULL COMMENT '市值 (USD)',
    forward_pe DECIMAL(10, 2) DEFAULT NULL COMMENT '預期市盈率',
    
    -- 時間戳
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    -- 索引
    UNIQUE KEY unique_symbol_date (symbol, data_date),
    INDEX idx_symbol (symbol),
    INDEX idx_date (data_date),
    INDEX idx_peg (peg_ratio),
    INDEX idx_inst_ownership (inst_ownership_pct)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='股票基本面和機構持股數據';


-- 擴展 market_data 表以包含技術指標（如果需要存儲 ATR）
-- 注意：ATR 通常在內存中計算，但可以選擇存儲以加快查詢
ALTER TABLE market_data 
ADD COLUMN IF NOT EXISTS atr_14 DECIMAL(10, 4) DEFAULT NULL COMMENT 'Average True Range (14-day)';


-- 創建視圖：合併市場數據和基本面數據
CREATE OR REPLACE VIEW vw_stock_analysis AS
SELECT 
    m.symbol,
    m.timestamp AS market_date,
    m.close AS price,
    m.volume,
    m.atr_14,
    f.peg_ratio,
    f.revenue_growth_yoy,
    f.inst_ownership_pct,
    f.pe_ratio,
    f.market_cap
FROM market_data m
LEFT JOIN stock_fundamentals f 
    ON m.symbol = f.symbol 
    AND DATE(m.timestamp) = f.data_date
ORDER BY m.symbol, m.timestamp DESC;


-- 插入示例基本面數據（供測試使用）
INSERT INTO stock_fundamentals 
(symbol, data_date, pe_ratio, peg_ratio, pb_ratio, revenue_growth_yoy, earnings_growth_yoy, inst_ownership_pct, inst_holders_count, market_cap)
VALUES
    ('AAPL', '2025-01-31', 28.5, 1.2, 45.3, 0.089, 0.12, 0.628, 4250, 2800000000000),
    ('NVDA', '2025-01-31', 65.2, 1.45, 50.8, 0.265, 0.38, 0.715, 3890, 2200000000000),
    ('TSLA', '2025-01-31', 78.3, 2.1, 12.4, 0.182, 0.22, 0.485, 2650, 950000000000),
    ('MSFT', '2025-01-31', 32.1, 1.35, 11.2, 0.115, 0.15, 0.742, 4580, 2500000000000),
    ('GOOGL', '2025-01-31', 24.8, 1.1, 5.8, 0.098, 0.11, 0.812, 3920, 1800000000000)
ON DUPLICATE KEY UPDATE 
    pe_ratio = VALUES(pe_ratio),
    peg_ratio = VALUES(peg_ratio),
    revenue_growth_yoy = VALUES(revenue_growth_yoy),
    inst_ownership_pct = VALUES(inst_ownership_pct),
    updated_at = CURRENT_TIMESTAMP;

-- 顯示創建成功的表
SELECT '✅ stock_fundamentals 表已創建' AS status;
SELECT '✅ market_data 表已擴展 (ATR 字段)' AS status;
SELECT '✅ vw_stock_analysis 視圖已創建' AS status;
