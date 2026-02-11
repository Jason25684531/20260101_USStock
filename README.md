# USStock - 美股量化交易系統

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10-blue.svg)](https://www.python.org/)
[![Docker](https://img.shields.io/badge/docker-compose-blue.svg)](https://www.docker.com/)

## 📖 概述

這是一套自動化的美股量化交易系統，採用微服務架構，支持多策略回測、**Alpaca Paper Trading 模擬交易**、自動調度、Line Bot 通知等功能。

### 主要特點

- 📈 **Paper Trading**: 整合 Alpaca API，支持無風險模擬交易（[詳細指南](PAPER_TRADING_GUIDE.md)）
- 🤖 **自動化調度**: APScheduler 每日美股收盤後自動執行策略分析
- 📱 **即時通知**: Line Bot 推送交易信號和每日摘要
- 📊 **多策略引擎**: Momentum, Value, Breakout, Acceleration, PEG, DuPont 等策略
- 🏆 **每日選股推薦**: 4 大規則策略 + ML 信心度評分 + 支撐壓力 → Top 5 推薦
- 🔐 **安全設計**: Docker Secrets 管理敏感資訊，零信任架構
- 🛡️ **風險控制**: 訂單上限保護、購買力驗證、Paper 模式硬編碼
- 📈 **Web Dashboard**: 視覺化回測結果和績效報告

## 🏗️ 系統架構

```
┌─────────────────────────────────────────────────────────────────┐
│                       Docker Compose 環境                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────┐    ┌───────────────┐    ┌───────────────┐    │
│  │   MySQL 8.0   │    │   Strategy    │    │      Web      │    │
│  │      db       │◄───│    Engine     │───►│   Dashboard   │    │
│  │  (Port:3308)  │    │  APScheduler  │    │  (Port:5000)  │    │
│  └──────────────┘    └───────┬───────┘    └───────┬───────┘    │
│                              │                     │            │
│                              │     Push Signal     │            │
│                              ▼                     ▼            │
│                    ┌───────────────────────────────────┐        │
│                    │       Line Messaging API          │        │
│                    │   (通知 + Webhook + Bot 命令)      │        │
│                    └───────────────────────────────────┘        │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## 📦 組件說明

| 服務 | 描述 | 技術棧 |
|------|------|--------|
| **db** | 資料庫服務 | MySQL 8.0, 持久化儲存 |
| **strategy_engine** | 策略執行引擎 | Python 3.10, VectorBT, APScheduler, Alpaca API |
| **web_dashboard** | Web 介面 + Line Bot | Flask, Chart.js, Line Bot SDK |

## 🎯 交易模式與策略類型

系統支持兩種運行模式和兩種策略類型，通過環境變數控制：

### 交易模式 (TRADING_MODE)

| 模式 | 說明 | 適用場景 |
|------|------|----------|
| **backtest** (默認) | 純回測模式，不執行真實交易 | 策略開發、歷史數據分析 |
| **paper** | Paper Trading 模擬交易 | 策略驗證、實戰測試 |
| **simulation** | 本地模擬交易 (MockBroker) | 離線測試、快速驗證 |

### 策略類型 (STRATEGY_TYPE)

| 類型 | 說明 | 使用方法 |
|------|------|----------|
| **traditional** (默認) | 動量 + 價值策略 | `export STRATEGY_TYPE=traditional` |
| **ml** | 機器學習策略 (XGBoost) | `export STRATEGY_TYPE=ml` |
| **screener** | 📊 每日選股推薦 | `export STRATEGY_TYPE=screener` |

**ML 策略特點**:
- 基於 XGBoost 分類器預測股票未來走勢
- 整合價格、宏觀、基本面三種數據源（**25 個特徵**，含技術指標 + 基本面）
- **Long-Only 策略**: BUY=做多，HOLD/SELL=持現金（不做空）
- **買入閾值 0.55**（`buy_threshold` 可配置，默認 0.55）
- 正則化防過擬合 (max_depth=5, lr=0.01, lambda=1.0, gamma=0.1)
- Early Stopping 機制 (20% 驗證集，patience=10)
- 輸出信號包含置信度 (confidence score 0-1)
- **Rel_Strength_SPY**: 63 日相對強度 (個股 vs SPY)
- **Volume_Price_Trend**: 10 日價量相關性
- **Top-N 信心度排名**: 僅保留 Top 5 最高信心 BUY 信號 (`ML_TOP_N` 可配置)
- **流動性過濾**: 20 日平均日交易額 < $5M 自動排除
- **交易成本模擬**: MockBroker 0.1% 手續費扣除（含滑點）

詳細說明請參閱 [Paper Trading 指南](doc/PAPER_TRADING_GUIDE.md) 和 [ML 平台指南](doc/ML_PLATFORM_GUIDE.md)。

### Walk-Forward 回測 & ML 監控

| 功能 | 說明 |
|------|------|
| **OOS 回測** | `python strategies/scripts/run_ml_backtest_2024.py --symbol AAPL --buy-threshold 0.55` (Gross + Net 權益曲線，Long-Only) |
| **Mock 宏觀數據** | `python scripts/populate_mock_macro.py` (FRED 不可用時填入基線數據) |
| **macro_data 防護** | `train_model.py` 自動建立 `macro_data` 表（若不存在） |
| **ML 狀態 API** | `GET /api/ml_status` — 模型特徵重要性 + 最近信號置信度 |
| **預測準確度圖** | `StrategyModel.plot_prediction_accuracy()` → `data/reports/prediction_accuracy.png` |

**DB 新欄位**: `trade_logs` 表新增 `confidence FLOAT` 和 `top_features JSON`，用於追蹤 ML 信號信心度。

## 🚀 快速開始

### 1. 環境準備

```bash
# 克隆專案
git clone <repo-url>
cd USStock

# 創建 secrets 目錄
mkdir .secrets
```

### 2. 配置 Secrets

在 `.secrets/` 目錄下創建以下文件：

```
.secrets/
├── db_root_password.txt    # MySQL root 密碼
├── db_password.txt         # 應用程式資料庫密碼
├── alpaca_key.txt          # Alpaca API Key (Paper Trading)
├── alpaca_secret.txt       # Alpaca API Secret (Paper Trading)
├── line_channel_token.txt  # Line Channel Access Token
├── line_channel_secret.txt # Line Channel Secret
└── line_user_id.txt        # 接收通知的 Line User ID
```

**💡 提示**: Alpaca Paper Trading 是免費的模擬交易服務，不需要真實資金。
前往 [Alpaca Markets](https://alpaca.markets/) 註冊並獲取 API 憑證。

### 3. 啟動服務

**開發環境**:
```bash
docker-compose up -d
```

**生產環境**:
```bash
docker-compose -f prod.docker-compose.yml up -d
```

### 4. 驗證服務

- **Web Dashboard**: http://localhost:5000
- **健康檢查**: http://localhost:5000/health

## 📱 Line Bot 設置

### 獲取 Line Bot 憑證

1. 前往 [Line Developers Console](https://developers.line.biz/)
2. 創建 Messaging API Channel
3. 記錄以下資訊：
   - Channel Access Token → `.secrets/line_channel_token.txt`
   - Channel Secret → `.secrets/line_channel_secret.txt`
4. 在 Line App 中掃描 QR Code 加好友
5. 在 Line 對 Bot 發送任意訊息，記錄您的 User ID → `.secrets/line_user_id.txt`

### 設置 Webhook

在 Line Developers Console 設置：
- **Webhook URL**: `https://your-domain.com/bot/callback`
- **Use webhook**: 開啟
- **Auto-reply messages**: 關閉

### 支援的 Bot 命令

| 命令 | 功能 |
|------|------|
| `/help` | 顯示幫助選單 |
| `/status` | 顯示系統狀態 |
| `/summary` | 獲取最新每日摘要 |
| `/positions` | 查看當前持倉 |
| `/strategies` | 列出可用策略 |

## ⏰ 自動調度

系統使用 APScheduler 在以下時間自動執行：

- **執行時間**: 週一至週五 16:15 EST (美股收盤後)
- **執行內容**: 
  1. 下載最新市場數據
  2. 執行所有策略分析
  3. 產生交易信號
  4. 發送 Line 通知

啟用調度模式需設置環境變數：
```bash
USE_SCHEDULER=true
```

## 📊 策略列表

### 回測策略

| 策略 | 描述 | 邏輯 |
|------|------|------|
| **Momentum** | 動量策略 | Close > 200日最高價 (VectorBT) |
| **Value** | 價值策略 | PE < 15 且 PB < 1.5 (VectorBT) |
| **ML Strategy** | 機器學習 | XGBoost 25特徵 (Long-Only) |

### 選股策略 (每日推薦)

| 策略 | 描述 | 通過條件 |
|------|------|----------|
| **Breakout** | 創新高動能 | 200日新高 + RSI>60 + SMA多頭排列 |
| **Acceleration** | 加速度指標 | 均速曲率上升 + 20日漲幅>0 |
| **PEG** | 本益成長比 | PEG<1.5 + ROE>10% + OCF>0 |
| **DuPont** | 杜邦分析 | ROE>5% + PB<8 + 資產周轉率>0.3 |

## 🏆 每日選股推薦

### 快速使用

```bash
# 基本掃描 (5 支股票)
python strategies/scripts/run_daily_screener.py --symbols AAPL,MSFT,NVDA,GOOGL,META --top-n 5

# 完整掃描 (51 股) + ML加權 + 存DB + Line通知
python strategies/scripts/run_daily_screener.py --use-ml --save-db --notify

# Walk-Forward 月度回測
python strategies/scripts/run_screener_backtest.py --months 12 --top-n 5
```

### 評分機制

- **規則分**: 4 策略各 0~1 分 (通過=1, 部分=score×0.5)
- **ML 信心度**: 0~1 分 (可選)
- **綜合分**: 0~5 分
- **BUY 條件**: ≥2 策略通過 或 總分≥2.0

### 支撐壓力

- SMA(60/120/200) 支撐壓力判定
- ATR(14)×1.5 動態帶寬
- 20日高低價區間

### 回測績效 (2025-02 → 2026-02)

| 指標 | 數值 |
|------|------|
| 策略總報酬 | +7.11% |
| 勝率 | 66.7% |
| 年化 Sharpe | 0.51 |
| 最大回撤 | -7.20% |

---

## 🔧 開發指南

### 本地開發

```bash
# 安裝依賴
pip install -r requirements.txt

# 運行測試
cd strategies
python test_local.py

# 測試 Line 通知
python test_line_notification.py
```

### 新增策略

1. 在 `strategies/src/strategies/` 創建新策略文件
2. 繼承基礎策略接口
3. 在 `main.py` 中註冊策略
4. 更新文檔

## 📁 專案結構

```
USStock/
├── .github/workflows/     # CI/CD 配置
├── .secrets/              # 敏感資訊 (git ignored)
├── database/              # 資料庫配置
│   ├── init/              # 初始化腳本
│   └── my.cnf             # MySQL 配置
├── openspec/              # 規格文檔
│   ├── changes/           # 變更提案
│   └── specs/             # 規格定義
├── strategies/            # 策略引擎
│   ├── src/
│   │   ├── config.py      # 🆕 共用常量與函式 (股票池/RSI/ATR/評分)
│   │   ├── adapters/      # 數據適配器
│   │   ├── core/          # 核心回測引擎
│   │   ├── ml/            # ML 模型 (XGBoost)
│   │   ├── screener/      # 每日選股引擎
│   │   │   ├── engine.py          # 選股主引擎
│   │   │   └── support_resistance.py  # 支撐壓力計算
│   │   ├── strategies/    # 策略實現
│   │   │   ├── momentum.py        # 動量 + Breakout + Acceleration
│   │   │   ├── fundamental.py     # PEG + DuPont 篩選
│   │   │   ├── value.py           # 價值策略
│   │   │   └── ml_strategy.py     # ML 策略
│   │   └── utils/         # 工具函數
│   ├── scripts/
│   │   ├── run_daily_screener.py   # 每日選股 CLI
│   │   └── run_screener_backtest.py  # 選股策略回測
│   └── tests/             # 測試文件
├── web/                   # Web 服務
│   ├── bot/               # Line Bot 處理器
│   ├── static/            # 靜態資源
│   └── templates/         # HTML 模板
├── docker-compose.yml     # 開發環境配置
├── prod.docker-compose.yml # 生產環境配置
└── README.md              # 本文件
```

## 📝 更新日誌

詳見 [updatelist.md](updatelist.md)

## 🔒 安全說明

- 所有敏感資訊使用 Docker Secrets 管理
- 生產環境不暴露資料庫端口
- Line Webhook 使用 HMAC-SHA256 簽名驗證
- Web Dashboard 使用 HTTP Basic Auth 保護

## 📄 授權

MIT License
