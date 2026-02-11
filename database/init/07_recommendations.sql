-- ============================================
-- 每日選股推薦結果表
-- ============================================
USE usstock;

CREATE TABLE IF NOT EXISTS daily_recommendations (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    scan_date DATE NOT NULL,
    symbol VARCHAR(10) NOT NULL,
    rank_position INT NOT NULL,
    signal_type ENUM('BUY', 'SELL') NOT NULL DEFAULT 'BUY',
    total_score DECIMAL(4, 2) NOT NULL COMMENT '綜合評分 0~5',
    
    -- 各策略通過狀態 (1=通過, 0=未通過)
    breakout_pass TINYINT(1) DEFAULT 0 COMMENT '創新高動能',
    acceleration_pass TINYINT(1) DEFAULT 0 COMMENT '加速度指標',
    peg_pass TINYINT(1) DEFAULT 0 COMMENT 'PEG選股',
    dupont_pass TINYINT(1) DEFAULT 0 COMMENT '杜邦分析',
    ml_confidence DECIMAL(4, 3) DEFAULT NULL COMMENT 'ML信心度 0~1',
    
    -- 價格與支撐壓力
    current_price DECIMAL(12, 4) NOT NULL,
    support_1 DECIMAL(12, 4) COMMENT '支撐價位1 (SMA最近)',
    support_2 DECIMAL(12, 4) COMMENT '支撐價位2 (ATR下緣)',
    resistance_1 DECIMAL(12, 4) COMMENT '壓力價位1 (SMA最近)',
    resistance_2 DECIMAL(12, 4) COMMENT '壓力價位2 (ATR上緣)',
    
    -- 基本面快照
    pe_ratio DECIMAL(10, 2),
    peg_ratio DECIMAL(10, 4),
    pb_ratio DECIMAL(10, 2),
    roe DECIMAL(10, 4),
    
    -- 策略明細 (JSON)
    strategy_details JSON COMMENT '各策略詳細評分與原因',
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    UNIQUE KEY uk_date_symbol (scan_date, symbol),
    INDEX idx_scan_date (scan_date),
    INDEX idx_total_score (total_score DESC),
    INDEX idx_signal (signal_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='每日選股推薦結果';
