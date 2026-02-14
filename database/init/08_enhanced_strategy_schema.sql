-- ============================================
-- 08_enhanced_strategy_schema.sql
-- v2 策略升級: 擴充基本面、籌碼面、選股結果欄位
-- ============================================

USE usstock;

-- 1. 擴展 stock_fundamentals 表 — 新增籌碼面 + 盈餘品質欄位
ALTER TABLE stock_fundamentals
    ADD COLUMN IF NOT EXISTS roe DECIMAL(10, 4) DEFAULT NULL COMMENT 'Return on Equity',
    ADD COLUMN IF NOT EXISTS insider_ownership_pct DECIMAL(10, 4) DEFAULT NULL COMMENT '內部人持股百分比',
    ADD COLUMN IF NOT EXISTS short_ratio DECIMAL(10, 2) DEFAULT NULL COMMENT '空頭覆蓋天數',
    ADD COLUMN IF NOT EXISTS short_pct_float DECIMAL(10, 4) DEFAULT NULL COMMENT '空頭佔流通股比例',
    ADD COLUMN IF NOT EXISTS gross_margin DECIMAL(10, 4) DEFAULT NULL COMMENT '毛利率',
    ADD COLUMN IF NOT EXISTS profit_margin DECIMAL(10, 4) DEFAULT NULL COMMENT '淨利率',
    ADD COLUMN IF NOT EXISTS free_cashflow BIGINT DEFAULT NULL COMMENT '自由現金流 (USD)',
    ADD COLUMN IF NOT EXISTS eps_growth_q DECIMAL(10, 4) DEFAULT NULL COMMENT '季度 EPS 成長率',
    ADD COLUMN IF NOT EXISTS sector VARCHAR(50) DEFAULT NULL COMMENT 'GICS 產業分類';

-- 2. 擴展 daily_recommendations 表 — 新增擴展策略欄位
ALTER TABLE daily_recommendations
    ADD COLUMN IF NOT EXISTS institutional_pass TINYINT(1) DEFAULT 0 COMMENT '籌碼面策略通過',
    ADD COLUMN IF NOT EXISTS volume_structure_pass TINYINT(1) DEFAULT 0 COMMENT '成交量結構策略通過',
    ADD COLUMN IF NOT EXISTS money_flow_pass TINYINT(1) DEFAULT 0 COMMENT '資金流向策略通過',
    ADD COLUMN IF NOT EXISTS multi_tf_momentum_pass TINYINT(1) DEFAULT 0 COMMENT '多時框動能策略通過',
    ADD COLUMN IF NOT EXISTS relative_strength_pass TINYINT(1) DEFAULT 0 COMMENT '相對強度策略通過',
    ADD COLUMN IF NOT EXISTS earnings_quality_pass TINYINT(1) DEFAULT 0 COMMENT '盈餘品質策略通過',
    ADD COLUMN IF NOT EXISTS sector_rotation_pass TINYINT(1) DEFAULT 0 COMMENT '產業輪動策略通過',
    ADD COLUMN IF NOT EXISTS total_strategies INT DEFAULT 4 COMMENT '總策略數量',
    ADD COLUMN IF NOT EXISTS sector VARCHAR(50) DEFAULT NULL COMMENT '個股所屬產業',
    ADD COLUMN IF NOT EXISTS macro_regime VARCHAR(10) DEFAULT NULL COMMENT '宏觀環境 (RISK_ON/NEUTRAL/RISK_OFF)';

-- 3. 建立產業動能追蹤表
CREATE TABLE IF NOT EXISTS sector_momentum (
    id INT AUTO_INCREMENT PRIMARY KEY,
    report_date DATE NOT NULL,
    sector VARCHAR(50) NOT NULL,
    etf_symbol VARCHAR(10) DEFAULT NULL,
    return_20d DECIMAL(10, 4) DEFAULT NULL COMMENT '20 日收益率',
    return_63d DECIMAL(10, 4) DEFAULT NULL COMMENT '63 日收益率',
    return_252d DECIMAL(10, 4) DEFAULT NULL COMMENT '252 日收益率',
    rank_position INT DEFAULT NULL COMMENT '動能排名',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_date_sector (report_date, sector),
    INDEX idx_report_date (report_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='產業動能追蹤';

-- 4. 建立宏觀環境紀錄表
CREATE TABLE IF NOT EXISTS macro_regime_log (
    id INT AUTO_INCREMENT PRIMARY KEY,
    report_date DATE NOT NULL,
    regime VARCHAR(10) NOT NULL COMMENT 'RISK_ON / NEUTRAL / RISK_OFF',
    vix DECIMAL(8, 2) DEFAULT NULL,
    yield_curve DECIMAL(8, 4) DEFAULT NULL COMMENT 'T10Y2Y',
    unemployment_rate DECIMAL(6, 2) DEFAULT NULL,
    fed_rate DECIMAL(6, 2) DEFAULT NULL,
    description TEXT DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_date (report_date),
    INDEX idx_regime (regime)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='宏觀環境分類紀錄';

SELECT '✅ 08_enhanced_strategy_schema.sql 執行完成' AS status;
