# 📚 深度操作指南 (ADVANCED REFERENCE)

進階用戶和開發者的完整指令參考。涵蓋 ML 訓練、回測、API 開發、測試與數據管理。

---

## 🤖 ML 模型訓練與評估

### 訓練本地模型（無數據庫）

適合離線開發或實驗環境。

```bash
# 訓練本地 XGBoost 模型（使用 yfinance 數據）
python strategies/train_local_model.py

# 參數說明
--symbols AAPL,MSFT,NVDA    # 訓練股票（默認: BACKTEST_SYMBOLS）
--years 2                    # 回溯年數（默認: 2）
--train-ratio 0.8            # 訓練集比例（默認: 0.8）
--validate-ratio 0.1         # 驗證集比例（默認: 0.1）
--test-ratio 0.1             # 測試集比例（默認: 0.1）

# 輸出
# - strategies/data/test_model.pkl — 訓練好的模型
# - strategies/data/scaler.pkl — 特徵正規化器
# - data/reports/prediction_accuracy.png — 預測準確度圖表
```

**適用場景：**
- 快速驗證新特徵
- 本地離線測試
- 實驗不同超參數

### 訓練數據庫模型（使用 MySQL 數據）

適合生產環境，使用 MySQL 中的歷史數據。

```bash
# 訓練 DB 版模型
python strategies/train_model.py

# 參數說明
--symbols AAPL,MSFT,NVDA    # 訓練股票（默認: 從 DB 讀取）
--market AAPL,MSFT          # 指定市場數據來源（默認: market_data 表）
--rebuild-macro             # 重新構建 macro_data（若缺失）
--use-cache true            # 使用緩存加速（默認: true）

# 預期行為
# 1. 自動檢查 macro_data 表，不存在則建立 (populate_mock_macro.py)
# 2. 從 DB 讀取 market_data + fundamentals
# 3. 計算 18 個 ML 特徵
# 4. 訓練 XGBoost 分類器 (買入/賣出/持有)
# 5. 儲存模型至 strategies/data/model.pkl

# 輸出
# - strategies/data/model.pkl — 生產模型
# - 模型特徵重要性存入 trade_logs.top_features JSON
```

**適用場景：**
- 日常定期訓練（每週或每月）
- Paper Trading 模擬交易
- 基於真實市場歷史數據的優化

### 模型評估與診斷

```bash
# 檢查模型狀態 API
curl -u admin:admin123 \
  'http://localhost:6688/api/ml_status'

# 響應包含
# - model_version: 模型創建時間
# - last_prediction: 最後預測時間
# - confidence_avg: 平均信心度
# - feature_importance: 特徵重要性排名
# - sample_signals: 最後 10 個預測信號

# 查看特徵重要性
# 在 Web Dashboard → ML Status 分頁 可視化查看
```

---

## 📈 Walk-Forward 回測

### 選股策略回測（月度滾動）

```bash
# 回測選股策略（4 個規則 + 可選 ML）
python strategies/scripts/run_screener_backtest.py \
  --months 12 \
  --top-n 5 \
  --use-ml auto \
  --buy-threshold 0.55

# 參數說明
--months 12          # 回測期間（月數）
--top-n 5            # 每日篩選 Top N 股票
--use-ml auto        # ML 使用模式: auto|true|false
--buy-threshold 0.55 # ML 買入閾值（0-1）
--start-date 2023-01-01  # 回測開始日期（可選）
--end-date 2025-12-31    # 回測結束日期（可選）

# 輸出
# - data/reports/screener_backtest_YYYY-MM-DD.csv
#   ├── date: 回測日期
#   ├── symbol: 股票代碼
#   ├── rank: 排名（1-5)
#   ├── raw_score: 規則分 (0-4)
#   ├── ml_confidence: ML 信心度 (若有)
#   └── composite_score: 最終評分
```

**監控指標：**
- **Gross Return**: 未扣交易成本的總報酬
- **Net Return**: 扣除 0.1% 手續費後的報酬
- **Sharpe Ratio**: 風險調整後的報酬
- **Max Drawdown**: 最大回撤

### ML 模型 Walk-Forward 回測（年度）

```bash
# 2024 全年 ML 策略回測
python strategies/scripts/run_ml_backtest_2024.py \
  --symbol AAPL \
  --buy-threshold 0.55 \
  --training-window 252 \
  --refit-frequency monthly

# 參數說明
--symbol AAPL           # 單支或多支股票 (AAPL,MSFT)
--buy-threshold 0.55    # ML 買入閾值
--training-window 252   # 訓練窗口（交易日數，默認 1 年）
--refit-frequency monthly|weekly  # 重新訓練頻率

# 輸出
# - data/reports/ml_backtest_2024_SYMBOL.csv
#   ├── date: 交易日期
#   ├── close: 收盤價
#   ├── prediction: ML 預測 (BUY/HOLD/SELL)
#   ├── confidence: 預測信心度 (0-1)
#   ├── position: 持倉狀態 (long/cash)
#   └── pnl: 日度損益
#
# - data/reports/ml_backtest_2024_SYMBOL_equity_curve.png
#   ├── Gross Equity: 毛淨值曲線
#   ├── Net Equity: 淨淨值曲線（扣手續費）
#   └── Drawdown: 回撤曲線
```

**Long-Only 策略說明：**
- BUY 信號 (confidence ≥ 0.55) → 開倉做多
- HOLD 信號 → 維持持倉
- SELL 信號 (confidence < 0.55) → 清倉
- 無持倉期間 → 持現金（不做空）

---

## 🔗 API 端點詳解

### 基本認證

所有 API 需使用 HTTP Basic Auth：

```bash
# 生成 Basic Auth Token
pair="admin:admin123"
token=$(echo -n "$pair" | base64)
# 或在 PowerShell
$token = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes('admin:admin123'))

# 在請求頭中使用
Authorization: Basic $token
```

### GET /api/recommendations

查詢推薦清單。

```bash
# 請求
curl -u admin:admin123 \
  'http://localhost:6688/api/recommendations?date=2026-02-15&limit=5&use_ml=true'

# 參數
date=2026-02-15      # 查詢日期（默認: 今天）
limit=5              # 返回前 N 個（默認: 5）
use_ml=true|false    # 是否包含 ML 信心度（默認: auto）

# 響應範例
{
  "date": "2026-02-15",
  "recommendations": [
    {
      "symbol": "AAPL",
      "rank": 1,
      "raw_score": 3.5,
      "ml_confidence": 0.72,
      "composite_score": 5.04,
      "signal": "BUY",
      "support": 185.5,
      "resistance": 195.2
    },
    ...
  ],
  "timestamp": "2026-02-15T16:00:00Z"
}
```

### GET /api/ml_status

查詢 ML 模型狀態與特徵重要性。

```bash
# 請求
curl -u admin:admin123 \
  'http://localhost:6688/api/ml_status'

# 響應範例
{
  "model_available": true,
  "model_version": "2026-02-10T10:30:00Z",
  "last_prediction": "2026-02-15T16:00:00Z",
  "confidence_avg": 0.68,
  "feature_importance": [
    {"feature": "rsi_14", "importance": 0.18},
    {"feature": "relative_strength", "importance": 0.15},
    {"feature": "momentum_20", "importance": 0.12},
    ...
  ],
  "sample_signals": [
    {"symbol": "AAPL", "prediction": "BUY", "confidence": 0.75},
    ...
  ]
}
```

### GET /api/macro

宏觀經濟數據。

```bash
# 請求
curl -u admin:admin123 \
  'http://localhost:6688/api/macro'

# 響應
{
  "as_of_date": "2026-02-15",
  "indicators": {
    "gdp_growth": 2.5,              # 季度 GDP 增速 (%)
    "unemployment_rate": 4.2,       # 失業率 (%)
    "inflation_rate": 2.1,          # 通脹率 (%)
    "fed_rate": 4.75,               # Fed 利率 (%)
    "yield_10y": 4.2,               # 10 年期收益率 (%)
    "vix": 12.5                     # VIX 波動率指數
  }
}
```

### GET /api/sectors

產業排名。

```bash
# 請求
curl -u admin:admin123 \
  'http://localhost:6688/api/sectors'

# 響應
{
  "as_of_date": "2026-02-15",
  "sectors": [
    {
      "name": "Technology",
      "performance": 1.5,     # 相對 S&P 500 的超額報酬 (%)
      "momentum": 0.8,        # 20 日動量
      "relative_strength": 1.2
    },
    ...
  ]
}
```

---

## 🧪 測試與驗證

### 模組編譯檢查

一次性檢查所有 Python 文件的語法。

```bash
# 檢查策略引擎（41 個文件）
python -m py_compile strategies/src/config.py
python -m py_compile strategies/src/main.py
python -m py_compile web/app.py
# ... （見 QUICK_START.md 第 1 步完整列表）

# 或批次檢查
find strategies/src web -name "*.py" -exec python -m py_compile {} \;
echo "All files compiled successfully"
```

### 單元測試運行

```bash
# 運行所有單元測試
cd strategies
python -m pytest tests/ -v

# 運行特定測試
python scripts/manual_checks/line_push.py --handler
python -m pytest tests/test_strategies.py::test_breakout -v

# 測試覆蓋率
python -m pytest tests/ --cov=src --cov-report=html
```

### 共用函式測試

驗證技術指標計算的正確性。

```bash
python << 'EOF'
import sys
sys.path.insert(0, 'strategies/src')
import pandas as pd
import numpy as np
from config import calc_rsi, calc_atr, calc_rule_score
from strategies.volume_analysis import calc_mfi, calc_cmf

# 測試 RSI
prices = pd.Series([44, 44.34, 44.09, ..., 45.64])  # 20+ 價格
rsi = calc_rsi(prices, period=14)
print(f"RSI(14) = {rsi.iloc[-1]:.2f}")  # 應為 50-70 範圍

# 測試 ATR
df = pd.DataFrame({
    'High': np.random.uniform(150, 160, 30),
    'Low': np.random.uniform(140, 150, 30),
    'Close': np.random.uniform(145, 155, 30)
})
atr = calc_atr(df, period=14)
print(f"ATR(14) = {atr.iloc[-1]:.4f}")  # 應為正數

# 測試 MFI、CMF
high = pd.Series(np.random.uniform(150, 160, 30))
low = pd.Series(np.random.uniform(140, 150, 30))
close = pd.Series(np.random.uniform(145, 155, 30))
vol = pd.Series(np.random.uniform(1e6, 5e6, 30))

mfi = calc_mfi(high, low, close, vol, period=14)
cmf = calc_cmf(high, low, close, vol, period=20)
print(f"MFI = {mfi.iloc[-1]:.2f}, CMF = {cmf.iloc[-1]:.4f}")
EOF
```

### 端到端測試

```bash
# 1. 啟動完整系統
docker-compose up -d
sleep 10  # 等待服務就緒

# 2. 測試 Web API
curl -u admin:admin123 http://localhost:6688/health
curl -u admin:admin123 http://localhost:6688/api/recommendations?limit=3

# 3. 測試 LineBot Webhook
curl -X POST http://localhost:6688/callback \
  -H "Content-Type: application/json" \
  -d '{"events":[]}'

# 4. 執行選股
python strategies/scripts/run_daily_screener.py \
  --symbols AAPL,MSFT,NVDA --top-n 3

# 5. 執行回測
python strategies/scripts/run_screener_backtest.py \
  --months 3 --top-n 5

# 預期結果: 無錯誤，輸出正常
```

---

## 💾 數據庫操作

### 連接到 MySQL

```bash
# 進入 DB 容器
docker-compose exec db mysql -u root -p

# 登入後執行 SQL
USE stock_db;
SHOW TABLES;

# 查看推薦表結構
DESCRIBE recommendations;

# 查看特定日期的推薦
SELECT symbol, raw_score, ml_confidence, composite_score 
FROM recommendations 
WHERE date = '2026-02-15' 
ORDER BY composite_score DESC 
LIMIT 5;
```

### 備份與還原

```bash
# 完整備份
docker-compose exec db mysqldump -u root -p stock_db > backup_2026-02-15.sql

# 還原備份
docker-compose exec db mysql -u root -p stock_db < backup_2026-02-15.sql

# 備份特定表
docker-compose exec db mysqldump -u root -p stock_db recommendations \
  > backup_recommendations.sql
```

### Schema 檢查與修改

```bash
# 查看所有表
docker-compose exec db mysql -u root -p -e "SHOW TABLES FROM stock_db;"

# 查看表大小
docker-compose exec db mysql -u root -p -e \
  "SELECT table_name, ROUND(((data_length + index_length) / 1024 / 1024), 2) 
   FROM information_schema.tables 
   WHERE table_schema = 'stock_db' 
   ORDER BY (data_length + index_length) DESC;"

# 增加新列（例如信心度）
docker-compose exec db mysql -u root -p -e \
  "ALTER TABLE stock_db.recommendations 
   ADD COLUMN IF NOT EXISTS confidence FLOAT DEFAULT 0;"

# 清空表（小心！）
docker-compose exec db mysql -u root -p -e \
  "TRUNCATE TABLE stock_db.recommendations;"
```

---

## 🔧 環境變數完整參考

### 核心變數

| 變數名 | 預設值 | 說明 | 範例 |
|--------|--------|------|------|
| `TRADING_MODE` | `backtest` | 交易模式 | `backtest`, `paper`, `simulation` |
| `STRATEGY_TYPE` | `traditional` | 策略類型 | `traditional`, `ml`, `screener` |
| `USE_SCHEDULER` | `false` | 啟用自動調度 | `true` / `false` |
| `USE_ML` | `auto` | ML 使用模式 | `true` / `false` / `auto` |
| `WEB_PORT` | `5000` | Web 服務端口 | `6688`, `8000` |

### 進階變數

| 變數名 | 預設值 | 說明 |
|--------|--------|------|
| `ML_TOP_N` | `5` | 返回的 Top-N BUY 信號 |
| `HYSTERESIS_THRESHOLD` | `0.15` | 持倉輪換防抖 (15%) |
| `MIN_VOLUME_USD` | `5000000` | 最小日交易額過濾 |
| `BUY_THRESHOLD` | `0.55` | ML 買入信心閾值 |
| `DB_HOST` | `localhost` | 數據庫主機 |
| `DB_PORT` | `3308` | 數據庫端口 |
| `LOG_LEVEL` | `INFO` | 日誌級別 (`DEBUG`, `INFO`, `WARN`) |

### 設置環境變數

```bash
# PowerShell
$env:TRADING_MODE = 'paper'
$env:USE_ML = 'true'
python strategies/src/main.py

# Bash
export TRADING_MODE=paper
export USE_ML=true
python strategies/src/main.py

# Docker Compose
# 編輯 .env 文件或在 docker-compose 命令中指定
docker-compose -e TRADING_MODE=paper up -d
```

---

## 📖 文檔導航

- **新手快速啟動** → [README.md](README.md#-立即啟動-3-步10-分鐘)
- **詳細配置步驟** → [QUICK_START.md](QUICK_START.md)
- **日常操作指令** → [COMMANDS_REFERENCE.md](COMMANDS_REFERENCE.md)
- **LineBot 完整設置** → [LINEBOT_SETUP.md](LINEBOT_SETUP.md)
- **系統架構與模式** → [doc/ML_PLATFORM_GUIDE.md](doc/ML_PLATFORM_GUIDE.md)
- **更新日誌** → [doc/updatelist.md](doc/updatelist.md)
