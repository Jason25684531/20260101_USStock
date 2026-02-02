# 更新日志

## 2026-02-02 - Alpaca Paper Trading 整合實施 ✅

### ✅ 已完成功能

#### 1. Alpaca Broker 適配器 (The Hands)
- **新建文件** (`strategies/src/adapters/broker.py`)
  - `AlpacaBroker` 類：完整的 Paper Trading 介面
  - **安全特性**:
    - 硬編碼 PAPER_BASE_URL 防止意外真實交易
    - MAX_ORDER_VALUE = $10,000 安全上限
    - 購買力驗證（買入前檢查）
    - 使用 `require_secret()` 安全加載 API 憑證
  - **核心方法**:
    - `get_account()`: 獲取帳戶資訊（現金、購買力、權益）
    - `get_positions()`: 獲取當前持倉
    - `get_current_price()`: 獲取實時價格
    - `check_risk()`: 預交易風險檢查
    - `submit_order()`: 提交訂單（市價/限價）
    - `cancel_order()`: 取消訂單
    - `close_position()`: 平倉

#### 2. 交易執行引擎整合 (The Brain)
- **修改文件** (`strategies/src/main.py`)
  - **TRADING_MODE 環境變數**:
    - `backtest`: 回測模式（默認）
    - `paper`: Paper Trading 模式（連接 Alpaca）
  - **新增 `execute_trades()` 函數**:
    1. 計算目標倉位（策略輸出）
    2. 獲取當前倉位（Alpaca API）
    3. 計算差異 (Diff = Target - Current)
    4. 執行調倉訂單（買入/賣出）
    5. 發送 Line 通知
  - **工作流程優化**:
    - Broker 僅在 paper 模式初始化
    - 價值策略僅在 backtest 模式運行（節省資源）
    - 實時帳戶資訊顯示

#### 3. 測試腳本
- **新建文件** (`strategies/test_broker_connection.py`)
  - 測試 Alpaca API 連接
  - 驗證帳戶資訊獲取
  - 測試持倉查詢
  - 測試價格獲取
  - 驗證風險檢查機制
- **新建文件** (`strategies/test_integration_logic.py`)
  - 模組導入驗證
  - 類別結構檢查
  - main.py 整合邏輯驗證
  - Docker 配置檢查
  - 依賴套件檢查

#### 4. 代碼重構與清理
- **消除重複代碼**:
  - 移除 `strategies/src/adapters/notifier.py` 中重複的 `get_secret()`
  - 移除 `web/app.py` 中重複的 `get_secret()`
  - 移除 `web/bot/handler.py` 中重複的 `get_secret()`
  - 新建 `web/security.py` 統一管理 Web 服務的 secrets
  - 所有模組統一使用 `utils.security` 或 `security` 模組
- **Secrets 文件整理**:
  - 創建 `.secrets/CLEANUP_GUIDE.md` 文檔
  - 識別並標記重複的 secrets 文件
  - 標準化命名規範（使用 .txt 擴展名）

#### 5. Docker 配置驗證
- **docker-compose.yml 已配置**:
  - `alpaca_key` secret 映射
  - `alpaca_secret` secret 映射
  - Strategy Engine 服務掛載 secrets
  - 支援 TRADING_MODE 環境變數

#### 6. 依賴套件
- **已確認** `strategies/requirements.txt`:
  - `alpaca-trade-api==3.0.2` ✅
  - 所有必要套件已列出

### 📋 使用說明

#### 啟動 Paper Trading 模式
```bash
# 方法 1: Docker (推薦)
docker-compose up -d
docker-compose exec strategy_engine bash -c "TRADING_MODE=paper python src/main.py"

# 方法 2: 本地執行
cd strategies
source venv/bin/activate  # Windows: .\venv\Scripts\Activate.ps1
export TRADING_MODE=paper  # Windows: $env:TRADING_MODE="paper"
python src/main.py
```

#### 測試 Broker 連接
```bash
cd strategies
python test_broker_connection.py  # 需要真實 API 憑證
python test_integration_logic.py  # 不需要憑證（邏輯驗證）
```

#### 設置 Alpaca API 憑證
1. 在 [Alpaca](https://alpaca.markets/) 註冊 Paper Trading 帳戶
2. 獲取 API Key 和 Secret
3. 填入憑證:
   ```bash
   echo "YOUR_API_KEY" > .secrets/alpaca_key.txt
   echo "YOUR_SECRET" > .secrets/alpaca_secret.txt
   ```

### ⚠️ 注意事項
- **PAPER_BASE_URL 已硬編碼** 為 `https://paper-api.alpaca.markets`，無法意外連接真實帳戶
- **訂單上限** 為 $10,000，防止胖手指錯誤
- **購買力驗證** 在提交訂單前執行
- **預設模式** 為 `backtest`，需要明確設置 `TRADING_MODE=paper` 才會執行真實交易

---

## 2026-01-31 - 自動化調度 & Line Bot 通知實施

### ✅ 已完成功能

#### 1. Line Bot 通知整合 (The Mouth)
- **Webhook 處理器** (`web/bot/handler.py`)
  - 實現 `/bot/callback` 端點接收 Line 事件
  - HMAC-SHA256 簽名驗證防止偽造攻擊
  - 支援命令: `/status`, `/help`, `/summary`, `/positions`, `/strategies`
  - Blueprint 架構易於維護和擴展

- **通知適配器** (`strategies/src/adapters/notifier.py`)
  - `LineNotifier` 類：統一管理 Line 推送
  - `send_signal()`: 發送交易信號 (📈BUY / 📉SELL)
  - `send_daily_summary()`: 發送每日摘要報告
  - `send_error_alert()`: 發送錯誤警報
  - 使用 Docker Secrets 安全管理憑證

#### 2. APScheduler 自動調度 (The Heartbeat)
- **調度器整合** (`strategies/src/main.py`)
  - 使用 `BlockingScheduler` + `CronTrigger`
  - 每週一至週五 16:15 EST 自動執行 (美股收盤後)
  - 環境變數 `USE_SCHEDULER=true` 啟用調度模式
  - 執行後自動發送每日摘要到 Line

#### 3. Docker 健康檢查 & 重啟策略
- **docker-compose.yml 更新**
  - 所有服務設置 `restart: always`
  - MySQL 健康檢查: `mysqladmin ping`
  - Web 健康檢查: `curl -f http://localhost:5000/health`
  - Strategy Engine 健康檢查: `python -c "import main"`
  - Line Bot Secrets 配置 (token, secret, user_id)

#### 4. 生產環境配置
- **prod.docker-compose.yml** (新建)
  - 移除資料庫端口暴露 (安全性)
  - 使用 Gunicorn 替代 Flask 開發服務器
  - 資源限制 (memory limits)
  - 生產環境變數配置

#### 5. CI/CD 腳手架
- **.github/workflows/deploy.yml** (新建)
  - GitHub Actions 自動部署模板
  - SSH 部署到 VPS
  - 健康檢查驗證

#### 6. 代碼清理
- **刪除重複文件**: `web/security.py` (與 `strategies/src/utils/security.py` 重複)
  - **更新 (2026-02-02)**: 恢復 `web/security.py`，因 web 和 strategies 是獨立服務
- **統一 get_secret()**: 在 `web/app.py` 中內聯實現，避免跨容器依賴
- **新增測試腳本**: `strategies/test_line_notification.py`

### 📁 文件變更摘要

| 類別 | 文件 | 變更類型 |
|------|------|----------|
| Line Bot | `web/bot/__init__.py` | 新建 |
| Line Bot | `web/bot/handler.py` | 新建 |
| 通知 | `strategies/src/adapters/notifier.py` | 新建 |
| 配置 | `prod.docker-compose.yml` | 新建 |
| CI/CD | `.github/workflows/deploy.yml` | 新建 |
| 測試 | `strategies/test_line_notification.py` | 新建 |
| 核心 | `strategies/src/main.py` | 修改 |
| Web | `web/app.py` | 修改 |
| 配置 | `docker-compose.yml` | 修改 |
| 依賴 | `strategies/requirements.txt` | 修改 |
| 依賴 | `web/requirements.txt` | 修改 |
| 清理 | `web/security.py` | 刪除 |

### 🔧 新增依賴

**strategies/requirements.txt**:
- `APScheduler==3.10.4` - 調度器
- `pytz==2023.3` - 時區處理
- `requests>=2.31.0` - HTTP 客戶端

**web/requirements.txt**:
- `requests>=2.31.0` - 內部 API 調用

### 📝 配置要求

**Line Bot Secrets** (放入 `.secrets/` 目錄):
```
.secrets/
├── line_channel_token.txt   # Line Channel Access Token
├── line_channel_secret.txt  # Line Channel Secret
└── line_user_id.txt         # 接收通知的 Line User ID
```

### 🚀 使用方式

**啟動調度模式** (生產環境):
```bash
docker-compose up -d
```

**啟動生產環境** (推薦):
```bash
docker-compose -f prod.docker-compose.yml up -d
```

**測試 Line Bot 通知**:
```bash
cd strategies
python test_line_notification.py
```

### 📊 架構圖

```
┌─────────────────────────────────────────────────────────────┐
│                    Docker Compose 環境                       │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────┐     ┌─────────────┐     ┌─────────────┐   │
│  │  MySQL 8.0  │     │  Strategy   │     │    Web      │   │
│  │     db      │◄────│   Engine    │────►│  Dashboard  │   │
│  │  Port:3308  │     │ APScheduler │     │  Port:5000  │   │
│  └─────────────┘     └──────┬──────┘     └──────┬──────┘   │
│                             │                    │          │
│                             ▼                    ▼          │
│                    ┌─────────────────────────────┐          │
│                    │      Line Messaging API      │         │
│                    │  (Push Notifications & Bot)  │         │
│                    └─────────────────────────────┘          │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---
**提交人**: Claude  
**日期**: 2026-01-31  
**狀態**: ✅ 自動化與通知功能完成

---

## 2025-12-31 - 基础设施搭建与 MVP 回测引擎完成

### ✅ 已完成功能

#### 1. Docker 微服务架构
- **Docker Compose 配置**
  - 定义 3 个服务：`db` (MySQL 8.0)、`strategy_engine` (Python)、`web_dashboard` (Flask)
  - 实现 Docker Secrets 安全管理（映射 `./.secrets/` 到 `/run/secrets/`）
  - 配置服务依赖和健康检查
  
- **数据库容器**
  - MySQL 8.0 服务配置（端口 3308）
  - 创建初始化脚本 `database/init/01_market_data.sql`
  - 定义 `market_data` 和 `strategy_signals` 数据表

#### 2. Python 与安全基础
- **安全模块** (`strategies/src/utils/security.py`)
  - 实现 `get_secret()` 函数，优先读取 `/run/secrets/`
  - 支持环境变量回退（本地开发）
  - 提供 `require_secret()` 和 `is_production()` 辅助函数
  
- **Dockerfiles**
  - `strategies/Dockerfile`：Python 3.10 + 数值计算依赖
  - `web/Dockerfile`：Flask + Gunicorn 配置
  - 固定版本依赖确保可重现构建

#### 3. 回测引擎核心
- **数据适配器** (`strategies/src/adapters/market_data.py`)
  - 使用 yfinance 获取历史 OHLCV 数据
  - 支持多股票批量获取
  - 网络故障时自动生成模拟数据
  
- **VectorBT 策略** (`strategies/src/core/backtest.py`)
  - 实现 SMA 双均线交叉策略
  - 完全向量化操作（无循环）
  - 生成详细性能报告（总回报、夏普比率、最大回撤等）
  
- **执行入口** (`strategies/src/main.py`)
  - 整合数据获取、策略执行、报告生成
  - 优雅的错误处理和日志输出
  - 支持 Docker 和本地开发环境

#### 4. 配置文件
- **依赖管理**
  - 根目录 `requirements.txt`：开发环境完整依赖
  - `strategies/requirements.txt`：策略引擎精简依赖
  - `web/requirements.txt`：Web 服务依赖
  - 修复版本冲突：`numpy==1.23.5`, `numba==0.56.4`, `plotly==5.14.1`
  
- **Git 配置**
  - 更新 `.gitignore` 排除敏感文件和构建产物

### 📊 测试结果

**测试命令**: `docker-compose up strategy_engine`

**输出示例**:
```
🚀 US Stock Trading System - Strategy Engine
Environment: Production (Docker)

📊 Fetching data for SPY (period=1y, interval=1d)...
⚠️  Using mock data generation (network unavailable)

🚀 Running SMA Strategy (Fast=20, Slow=50)...
✅ Backtest completed! Total trades: 3

📊 BACKTEST PERFORMANCE REPORT - SPY
============================================================
💰 Financial Metrics:
   Start Value:      $10,000.00
   End Value:        $10,667.11
   Total Return:     6.67%
   Max Drawdown:     16.51%

📈 Performance Ratios:
   Sharpe Ratio:     0.48
   Calmar Ratio:     0.59
   Win Rate:         0.0%

📊 Trade Statistics:
   Total Trades:     3
============================================================

✅ Strategy execution completed successfully!
```

### 🔧 技术栈确认
- **基础设施**: Docker Compose
- **语言**: Python 3.10
- **核心库**: vectorbt 0.25.5, pandas 2.0.3, yfinance 0.2.28
- **数据库**: MySQL 8.0
- **安全**: Docker Secrets + 零信任架构

### 📝 已知问题与限制
1. **网络访问**: 容器内 yfinance 可能受限，已实现模拟数据回退机制
2. **Web Dashboard**: 仅完成 Dockerfile 搭建，功能待实现
3. **端口冲突**: 修改 MySQL 端口为 3308 以避免冲突

### 🚀 下一步计划
1. 实现 Web Dashboard 基础页面
2. 添加更多回测策略（RSI、MACD、布林带等）
3. 实现策略性能对比功能
4. 连接 Alpaca API 进行实盘交易准备
5. 集成 LineBot 通知系统

---
**提交人**: Claude  
**日期**: 2025-12-31  
**状态**: ✅ MVP 完成并通过测试
