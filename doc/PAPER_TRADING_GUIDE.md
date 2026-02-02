# 📈 Paper Trading 模擬交易指南

## 概述

本系統已整合 **Alpaca Paper Trading API**，支持無風險的模擬交易，讓您在真實市場環境中測試策略表現。

## 🎯 功能特點

### 1. 雙模式運行
- **Backtest 模式**（默認）: 純回測分析，不執行交易
- **Paper Trading 模式**: 連接 Alpaca，執行真實模擬交易

### 2. 安全保護機制
- ✅ **硬編碼 Paper 端點**: `PAPER_BASE_URL = "https://paper-api.alpaca.markets"`
- ✅ **訂單上限**: 單筆訂單上限 $10,000（防止胖手指錯誤）
- ✅ **購買力驗證**: 買入前檢查資金是否充足
- ✅ **預交易風險檢查**: 所有訂單提交前必須通過風險檢查

### 3. 自動化交易流程
1. **計算目標倉位**: 策略輸出買入/賣出信號
2. **獲取當前倉位**: 從 Alpaca API 查詢實際持倉
3. **計算差異**: `Diff = Target - Current`
4. **執行調倉**: 自動提交市價單
5. **發送通知**: Line Bot 推送交易執行結果

## 🚀 快速開始

### 步驟 1: 註冊 Alpaca Paper Trading 帳戶

1. 前往 [Alpaca Markets](https://alpaca.markets/) 註冊（完全免費）
2. 選擇 **Paper Trading** 模式（使用模擬資金 $100,000）
3. 在 Dashboard 中生成 API Key 和 Secret

### 步驟 2: 配置 API 憑證

將憑證填入 `.secrets/` 目錄：

```bash
cd d:\01_Project\20260101_USStock

# 創建 Alpaca 憑證文件
echo "YOUR_API_KEY_HERE" > .secrets/alpaca_key.txt
echo "YOUR_SECRET_HERE" > .secrets/alpaca_secret.txt
```

### 步驟 3: 測試連接

```bash
cd strategies

# 激活虛擬環境
.\venv\Scripts\Activate.ps1

# 邏輯驗證（不需要 API 憑證）
python test_integration_logic.py

# 實際連接測試（需要 API 憑證）
python test_broker_connection.py
```

**預期輸出**:
```
===========================================================
🧪 Alpaca Broker 連接測試
===========================================================

【步驟 1】 初始化 Alpaca Broker...
✅ Connected to Alpaca Paper Trading
   Account ID: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
   Buying Power: $100,000.00
✅ Broker 初始化成功

【步驟 2】 獲取帳戶資訊...
✅ 帳戶資訊:
   現金餘額: $100,000.00
   購買力: $100,000.00
   總權益: $100,000.00
   投資組合價值: $0.00

...
```

### 步驟 4: 啟動 Paper Trading 模式

#### 方法 1: Docker (推薦)

修改 `docker-compose.yml`:

```yaml
strategy_engine:
  environment:
    - TRADING_MODE=paper  # 添加此行
```

然後重啟服務:
```bash
docker-compose down
docker-compose up -d
```

#### 方法 2: 本地執行

```bash
cd strategies
.\venv\Scripts\Activate.ps1

# 設置環境變數
$env:TRADING_MODE="paper"

# 運行策略引擎
python src/main.py
```

#### 方法 3: 調度器模式（生產環境）

```bash
$env:TRADING_MODE="paper"
$env:USE_SCHEDULER="true"
python src/main.py
```

## 📊 運行流程說明

### Backtest 模式 (TRADING_MODE=backtest 或未設置)

```
1. 下載市場數據 (SPY, QQQ, AAPL, NVDA)
2. 執行動量策略 → 生成信號
3. 執行價值策略 → 生成信號
4. 保存回測結果到 MySQL
5. 發送 Line 通知（交易信號）
```

### Paper Trading 模式 (TRADING_MODE=paper)

```
1. 下載市場數據 (SPY, QQQ, AAPL, NVDA)
2. 連接 Alpaca Broker
3. 獲取帳戶資訊 (現金、購買力、權益)
4. 執行動量策略 → 計算目標倉位
5. 獲取當前倉位 (從 Alpaca)
6. 計算差異 (Target - Current)
7. 執行訂單:
   - 買入: 當 Diff > 0
   - 賣出: 當 Diff < 0
   - 跳過: 當 Diff = 0
8. 發送 Line 通知（交易執行結果）
9. 更新帳戶權益
```

## 🛡️ 風險管理

### 訂單前檢查

所有訂單在提交前都會經過 `check_risk()` 函數驗證：

```python
# 檢查 1: 訂單金額上限
if order_value > $10,000:
    ❌ 拒絕訂單

# 檢查 2: 購買力驗證（僅限買單）
if qty > 0 and order_value > buying_power:
    ❌ 拒絕訂單

# 檢查通過
✅ 提交訂單
```

### 範例

```python
# 範例 1: 正常訂單
Symbol: AAPL, Qty: 10, Price: $150
Order Value: $1,500 < $10,000 ✅
Buying Power: $100,000 > $1,500 ✅
→ 訂單通過

# 範例 2: 超額訂單
Symbol: NVDA, Qty: 100, Price: $500
Order Value: $50,000 > $10,000 ❌
→ 拒絕: "Order value $50,000 exceeds safety cap of $10,000"

# 範例 3: 購買力不足
Symbol: TSLA, Qty: 100, Price: $200
Order Value: $20,000
Buying Power: $5,000 < $20,000 ❌
→ 拒絕: "Insufficient buying power"
```

## 📱 Line 通知範例

### 回測模式通知

```
📊 交易信號

標的: AAPL
動作: 📈 買入
價格: $150.25
原因: 動量突破信號
策略: Momentum
時間: 2026-02-02 16:30 EST
```

### Paper Trading 模式通知

```
💰 訂單執行

標的: AAPL
動作: 📈 買入
數量: 10 股
價格: $150.25
原因: 策略調倉: 0 -> 10
策略: Paper Trading
訂單ID: abc123...
狀態: filled
時間: 2026-02-02 16:30 EST

帳戶權益: $98,497.50
```

## 🔧 進階配置

### 調整策略邏輯

目前策略使用簡單的固定數量邏輯：

```python
# strategies/src/main.py, Line ~80
if last_trade['Exit Timestamp'] is None:  # 持倉中
    target_positions[symbol] = 10  # 持有 10 股
else:
    target_positions[symbol] = 0   # 空倉
```

您可以修改為基於權益百分比的動態倉位：

```python
account = broker.get_account()
position_size = account['equity'] * 0.10  # 每個標的 10% 權益
target_qty = int(position_size / current_price)
target_positions[symbol] = target_qty
```

### 添加更多策略

在 Paper Trading 模式下，您可以取消價值策略的跳過邏輯：

```python
# strategies/src/main.py, Line ~135
if TRADING_MODE == 'backtest':  # 移除此條件
    # 價值策略代碼
```

### 自定義通知格式

修改 `strategies/src/adapters/notifier.py` 中的 `send_signal()` 函數。

## ❓ 常見問題

### Q1: 為什麼我無法連接到 Alpaca？

**A**: 請檢查：
1. API 憑證是否正確填入 `.secrets/alpaca_key.txt` 和 `alpaca_secret.txt`
2. 網絡連接是否正常
3. 是否選擇了 Paper Trading 帳戶（不是 Live Trading）

### Q2: 訂單為什麼被拒絕？

**A**: 可能原因：
1. 訂單金額超過 $10,000
2. 購買力不足
3. 標的不可交易（市場關閉或股票暫停交易）

### Q3: 如何查看訂單歷史？

**A**: 
1. 登入 [Alpaca Dashboard](https://app.alpaca.markets/)
2. 查看 "Orders" 和 "Positions" 頁面
3. 或使用 `broker.get_order(order_id)` API

### Q4: Paper Trading 和真實交易有什麼區別？

**A**: Paper Trading 使用模擬資金和模擬訂單，但：
- ✅ 使用真實市場數據
- ✅ 訂單執行邏輯與真實交易相同
- ✅ 滑點和成交延遲會被模擬
- ❌ 不會真正扣款或入帳

### Q5: 如何切換回 Backtest 模式？

**A**: 
```bash
# 移除或註釋 TRADING_MODE 環境變數
# Docker
docker-compose down
# 編輯 docker-compose.yml，移除 TRADING_MODE=paper
docker-compose up -d

# 本地
Remove-Item Env:\TRADING_MODE  # PowerShell
python src/main.py
```

## 📚 延伸閱讀

- [Alpaca API 文檔](https://alpaca.markets/docs/)
- [VectorBT 回測框架](https://vectorbt.dev/)
- [APScheduler 調度器](https://apscheduler.readthedocs.io/)

## 🆘 支持

如有問題，請：
1. 查看 [updatelist.md](../updatelist.md) 了解最新更新
2. 運行 `test_integration_logic.py` 驗證代碼邏輯
3. 檢查 Docker logs: `docker-compose logs strategy_engine`
4. 提交 Issue 到 GitHub Repository

---

**⚠️ 免責聲明**: 本系統僅供學習和研究使用。Paper Trading 雖然無風險，但真實交易涉及資金損失風險，請謹慎操作。
