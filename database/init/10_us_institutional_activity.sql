-- ============================================
-- 10_us_institutional_activity.sql
-- US holder / fund / insider activity snapshot cache
-- ============================================

USE usstock;

CREATE TABLE IF NOT EXISTS us_institutional_activity (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    symbol VARCHAR(16) NOT NULL COMMENT '股票代碼',
    snapshot_date DATE NOT NULL COMMENT '本次抓取快照日期',
    institution_report_date DATE NULL COMMENT '機構持股揭露日期',
    mutualfund_report_date DATE NULL COMMENT '共同基金持股揭露日期',
    institution_holders_count INT NULL COMMENT '機構持有人數（來源資料筆數）',
    institution_total_shares BIGINT NULL COMMENT '機構持股總股數（來源聚合）',
    institution_total_value BIGINT NULL COMMENT '機構持股總市值（來源聚合）',
    institution_avg_pct_change DECIMAL(18, 8) NULL COMMENT '機構持股平均變動率',
    mutualfund_holders_count INT NULL COMMENT '共同基金持有人數（來源資料筆數）',
    mutualfund_total_shares BIGINT NULL COMMENT '共同基金持股總股數（來源聚合）',
    mutualfund_total_value BIGINT NULL COMMENT '共同基金持股總市值（來源聚合）',
    mutualfund_avg_pct_change DECIMAL(18, 8) NULL COMMENT '共同基金持股平均變動率',
    insider_buys_6m BIGINT NULL COMMENT '內部人近 6 個月買入股數',
    insider_sells_6m BIGINT NULL COMMENT '內部人近 6 個月賣出股數',
    insider_net_shares_6m BIGINT NULL COMMENT '內部人近 6 個月淨買賣股數',
    insider_total_transactions_6m INT NULL COMMENT '內部人近 6 個月總交易次數',
    insider_total_shares_held BIGINT NULL COMMENT '內部人合計持股',
    source VARCHAR(64) NOT NULL DEFAULT 'yfinance-holders' COMMENT '資料來源',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    UNIQUE KEY uk_symbol_snapshot_source (symbol, snapshot_date, source),
    INDEX idx_symbol_snapshot (symbol, snapshot_date DESC),
    INDEX idx_institution_report_date (institution_report_date),
    INDEX idx_mutualfund_report_date (mutualfund_report_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='美股機構 / 共同基金 / 內部人活動快照';

SELECT '✅ us_institutional_activity 表已創建' AS status;