# 更新日志

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
