# Pure Local Simulation Guide

## 概述

本地模擬交易模式 (Pure Local Simulation) 提供完全獨立於外部 API 的交易模擬環境。使用 Yahoo Finance 獲取真實市場數據，並通過 MockBroker 模擬交易執行。

## 特點

✅ **零外部依賴**: 不需要 Alpaca 帳號或 API Key  
✅ **真實數據**: 使用 yfinance 獲取真實市場數據  
✅ **即時執行**: 模擬市價訂單的即時成交  
✅ **狀態持久化**: JSON + MySQL 雙重保存  
✅ **完整記錄**: 所有交易記錄至資料庫  

## 快速開始

### 1. 本地測試

```bash
# 進入策略目錄
cd strategies

# 創建並激活虛擬環境（如果還沒有）
python -m venv venv
venv\Scripts\activate  # Windows
# 或
source venv/bin/activate  # Linux/Mac

# 安裝依賴
pip install -r requirements.txt

# 測試 MockBroker
python test_mock_broker.py
```

### 2. Docker 環境運行

```bash
# 確保 docker-compose.yml 中設置了 TRADING_MODE=simulation
# 已經預設配置完成

# 啟動所有服務
docker-compose up -d

# 查看策略引擎日誌
docker logs -f usstock_strategy_engine

# 停止服務
docker-compose down
```

## 交易模式對比

| 模式 | 說明 | 需要 API | 執行方式 | 適用場景 |
|------|------|----------|----------|----------|
| `backtest` | 回測模式 | ❌ | 歷史數據驗證 | 策略開發與驗證 |
| `simulation` | 本地模擬 | ❌ | MockBroker 即時模擬 | 實盤前測試 |
| `paper` | Alpaca Paper Trading | ✅ | Alpaca API | 需要 Alpaca 環境 |

## MockBroker 功能

### 初始設置
- **起始資金**: $100,000
- **狀態文件**: `/app/data/mock_broker_state.json`
- **交易記錄**: MySQL `trade_logs` 表

### 支援操作

```python
from adapters.broker import MockBroker

# 初始化
broker = MockBroker()

# 查詢帳戶
account = broker.get_account()
print(f"現金: ${account['cash']:,.2f}")

# 查詢持倉
positions = broker.get_positions()
print(f"持倉: {positions}")

# 買入
order = broker.submit_order(
    symbol='AAPL',
    qty=10,
    side='buy',
    current_price=150.00  # 可選，不提供則自動從 yfinance 獲取
)

# 賣出
order = broker.submit_order(
    symbol='AAPL',
    qty=5,
    side='sell'
)

# 平倉
broker.close_position('AAPL')
```

### 風險控制

- ✅ 單筆訂單上限: $10,000
- ✅ 買入前檢查現金餘額
- ✅ 賣出前檢查持股數量
- ✅ 防止透支交易

## 數據來源

### Yahoo Finance (yfinance)
- 即時價格獲取
- 歷史 OHLCV 數據
- 基本面數據 (PE/PB/PEG)

### FRED API (fredapi) - 可選
- 宏觀經濟指標
- GDP、失業率等
- 需要設置 `FRED_API_KEY` 環境變數

## 環境變數配置

在 `.env` 文件中設置：

```bash
# 交易模式
TRADING_MODE=simulation

# 資料庫配置
DB_HOST=db
DB_PORT=3306
DB_USER=root
DB_NAME=usstock
DB_ROOT_PASSWORD=your_password

# 可選：FRED API（宏觀數據）
FRED_API_KEY=your_fred_api_key

# 可選：Line 通知
LINE_CHANNEL_ACCESS_TOKEN=your_token
```

## 常見問題

### Q: 如何重置 MockBroker 狀態？
A: 刪除 `data/mock_broker_state.json` 文件，下次運行會自動創建新狀態（$100k 起始資金）。

### Q: 交易記錄保存在哪裡？
A: 
- **短期**: JSON 文件 (`data/mock_broker_state.json`)
- **長期**: MySQL `trade_logs` 表

### Q: 如何切換回 Alpaca Paper Trading？
A: 修改 `docker-compose.yml` 中的 `TRADING_MODE=paper` 並設置 Alpaca API keys。

### Q: 價格獲取失敗怎麼辦？
A: `get_latest_price()` 會自動重試並回退至日線數據。如果仍失敗，需要手動提供 `current_price` 參數。

## 架構圖

```
┌─────────────────────────────────────────────────┐
│              Trading Strategy Engine            │
│                  (main.py)                      │
└───────────────────┬─────────────────────────────┘
                    │
        ┌───────────┴───────────┐
        │                       │
        ▼                       ▼
┌───────────────┐       ┌──────────────┐
│  MockBroker   │       │ Market Data  │
│  (本地模擬)    │       │  (yfinance)  │
└───────┬───────┘       └──────┬───────┘
        │                      │
        ▼                      ▼
┌──────────────────────────────────────┐
│          MySQL Database              │
│  - trade_logs (交易記錄)              │
│  - market_data (市場數據)             │
│  - backtest_runs (回測結果)           │
└──────────────────────────────────────┘
```

## 測試結果

所有測試均通過 ✅ (2026-02-09)

```
【測試 1】初始化 MockBroker - ✅
【測試 2】查詢帳戶資訊 - ✅
【測試 3】查詢持倉 - ✅
【測試 4】獲取市場價格 (yfinance) - ✅
【測試 5】執行買入訂單 - ✅
【測試 6】查詢更新後的帳戶 - ✅
【測試 7】執行賣出訂單 - ✅
【測試 8】最終狀態驗證 - ✅
【測試 9】平倉功能 - ✅
```

實際交易測試：
- 買入 5 股 AAPL @ $278.08 ✅
- 賣出 2 股 AAPL @ $291.98 ✅
- 平倉 3 股 AAPL @ $278.08 ✅
- 最終盈虧: +$27.81 ✅

## 後續開發

計劃支援的功能：
- [ ] 限價單支援
- [ ] 止損單支援
- [ ] 部分成交模擬
- [ ] 滑點模擬
- [ ] 手續費計算
- [ ] Google Trends 整合 (pytrends)

## 相關文件

- [OpenSpec 任務清單](../openspec/switch-to-local-simulation/tasks.md)
- [更新日誌](./updatelist.md)
- [Alpaca Paper Trading 指南](./PAPER_TRADING_GUIDE.md)

---

**作者**: Quant System  
**更新日期**: 2026-02-09  
**版本**: 1.0.0
