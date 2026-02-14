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
│  │  (Port:3308)  │    │  (Port:5001)  │    │  (Port:6688)  │    │
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
- 整合價格、技術指標數據（**18 個特徵**，純技術面）
- **ML 信心度加權**：`Rating = Raw_Score × (Confidence / 0.5)`（ML 看好時放大評分）
- **Long-Only 策略**: BUY=做多，HOLD/SELL=持現金（不做空）
- **買入閾值 0.55**（`buy_threshold` 可配置，默認 0.55）
- 正則化防過擬合 (max_depth=5, lr=0.01, lambda=1.0, gamma=0.1)
- Early Stopping 機制 (20% 驗證集，patience=10)
- 輸出信號包含置信度 (confidence score 0-1)
- **Rel_Strength_SPY**: 63 日相對強度 (個股 vs SPY)
- **Volume_Price_Trend**: 10 日價量相關性
- **Top-N 信心度排名**: 僅保留 Top 5 最高信心 BUY 信號 (`ML_TOP_N` 可配置)
- **Hysteresis Filter**: 持倉輪換防抖 — 新信號需高出 15% confidence 才替換 (`HYSTERESIS_THRESHOLD` 可配置)
- **流動性過濾**: 20 日平均日交易額 < $5M 自動排除
- **交易成本模擬**: MockBroker 0.1% 手續費扣除（含滑點）
- **Anti-Bias 回測**: `backtest_strategy()` 使用 Point-in-time 基本面，防止前瞻偏差

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

- **Web Dashboard**: http://localhost:6688
- **健康檢查**: http://localhost:6688/health

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
- **Webhook URL**: `https://your-domain.ngrok-free.app/callback`
- **Use webhook**: 開啟
- **Auto-reply messages**: 關閉

本地開發時使用 Ngrok 轉發：
```bash
ngrok http 6688
```

### 支援的 Bot 命令

| 命令 | 功能 | 回覆格式 |
|------|------|----------|
| `Top5` | 🏆 今日選股推薦 Top 5（完整版：規則 + ML 加權） | Flex Carousel |
| `Top5基礎` | 📊 今日選股推薦 Top 5（純規則版：無 ML 加權） | Flex Carousel |
| `ML AAPL` | 🤖 查詢單支股票 ML 預測 | Text |
| `/status` | 📊 顯示系統狀態 | Text |
| `/strategies` | 📈 列出可用策略與版本差異 | Text |
| `/help` | ❓ 顯示幫助選單 | Text |

**推薦版本差異：**
- **Top5（完整版）** — 評分 = 規則分 × (ML 信心度 / 0.5)，顯示 ML 百分比
- **Top5基礎（純規則版）** — 評分 = 純規則分 (0-4)，ML 顯示為「—」
- **切換方式** — 直接輸入命令名稱即可查看不同版本

### 🤖 ML 信心度自動啟用

**ML 信心度會自動顯示**，條件如下：

| 情景 | ML 顯示 | 說明 |
|------|--------|------|
| `data/model.pkl` 或 `test_model.pkl` 存在 | `72%`（數值） | 系統自動啟用 ML |
| 模型文件不存在 | `—` | 無 ML 模型可用 |
| `--use-ml false` | `—` | 用戶禁用 ML |

**運行指令：**
```bash
# 📌 推薦：自動偵測 ML 模型（最簡單）
python strategies/scripts/run_daily_screener.py --save-db --notify

# ✅ 強制啟用 ML（即使沒有模型，會拋出錯誤）
python strategies/scripts/run_daily_screener.py --use-ml true --save-db

# ❌ 禁用 ML（純規則推薦）
python strategies/scripts/run_daily_screener.py --use-ml false --save-db
```

---

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
| **ML Strategy** | 機器學習 | XGBoost 18特徵 (Long-Only) |

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

# 完整掌描 (51 股) + ML加權 + 存DB + LINE Flex 通知
python strategies/scripts/run_daily_screener.py --use-ml --save-db --notify

# Walk-Forward 月度回測
python strategies/scripts/run_screener_backtest.py --months 12 --top-n 5
```

### 評分機制

- **規則分**: 4 策略各 0~1 分 (通過=1, 部分=score×0.5)
- **ML 信心度**: 0~1（可選）
- **綜合分**: `Rating = Raw_Score × (Confidence / 0.5)`（僅當 ML 判定 BUY）
- **無 ML 或非 BUY**: 維持 `Raw_Score`（範圍 0~4）
- **BUY 條件**: ≥2 策略通過 或 總分≥2.0

### 支撐壓力

- SMA(60/120/200) 支撐壓力判定
- ATR(14)×1.5 動態帶寬
- 20日高低價區間

### 回測績效說明

- 回測結果使用 yfinance 即時調整後數據，會隨市場資料更新而變動。
- 建議使用下列指令在本機即時重算：

```bash
python strategies/scripts/run_screener_backtest.py --months 12 --top-n 5
```

---

## 🔧 開發指南

### 本地開發

```bash
# 安裝依賴
pip install -r requirements.txt

# 每日選股（無 ML）
python strategies/scripts/run_daily_screener.py --symbols AAPL,MSFT,NVDA,GOOGL,META --top-n 3

# 每日選股（ML 加權）
python strategies/scripts/run_daily_screener.py --symbols AAPL,MSFT,NVDA,GOOGL,META --top-n 3 --use-ml

# Walk-Forward 回測
python strategies/scripts/run_screener_backtest.py --months 12 --top-n 5
```

### 新增策略

1. 在 `strategies/src/strategies/` 創建新策略文件
2. 繼承基礎策略接口
3. 在 `main.py` 中註冊策略
4. 更新文檔

## 📁 專案結構

```
USStock/
├── .secrets/                  # 🔒 敏感資訊 (git ignored)
├── data/
│   └── reports/               # 回測報告輸出 (CSV, PNG)
├── database/                  # 資料庫配置
│   ├── my.cnf                 # MySQL 配置
│   └── init/                  # DB 初始化腳本
│       ├── 01_market_data.sql
│       ├── 02_trade_logs.sql
│       ├── 05_fundamental_chips.sql
│       ├── 06_macro_sentiment.sql
│       └── 07_recommendations.sql
├── doc/                       # 文件資料
│   ├── AGENTS.md              # AI Agent 協作規範
│   ├── CLAUDE.md              # Claude AI 開發規則
│   ├── LOCAL_SIMULATION_GUIDE.md
│   ├── ML_PLATFORM_GUIDE.md
│   └── updatelist.md          # 更新日誌
├── openspec/                  # 開發規格與提案
│   ├── AGENTS.md
│   ├── project.md
│   └── changes/               # 變更提案歷史
├── scripts/                   # 全域工具腳本
│   ├── migrate_secrets_to_env.py
│   └── populate_mock_macro.py
├── strategies/                # 🧠 策略引擎服務
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── train_model.py         # DB 版模型訓練
│   ├── data/                  # 模型文件 (model.pkl)
│   ├── src/
│   │   ├── config.py          # 共用常量與函式 (股票池/RSI/ATR/評分)
│   │   ├── main.py            # 策略入口 (APScheduler 調度)
│   │   ├── adapters/          # 外部服務適配器
│   │   │   ├── broker.py      #   MockBroker / Alpaca 接口
│   │   │   ├── database.py    #   DatabaseAdapter (MySQL CRUD)
│   │   │   ├── market_data.py #   yfinance 市場數據
│   │   │   └── notifier.py    #   LINE 推播通知
│   │   ├── core/
│   │   │   └── backtest.py    #   VectorBT 回測引擎 (ATR 追蹤停損)
│   │   ├── ml/
│   │   │   ├── features.py    #   ML 特徵工程 (18 個特徵)
│   │   │   └── model.py       #   StrategyModel (XGBoost 訓練/預測)
│   │   ├── screener/
│   │   │   ├── engine.py      #   每日選股主引擎
│   │   │   └── support_resistance.py  # 支撐壓力計算
│   │   ├── strategies/
│   │   │   ├── momentum.py    #   動量 + Breakout + Acceleration
│   │   │   ├── fundamental.py #   PEG + DuPont 篩選
│   │   │   ├── value.py       #   價值策略
│   │   │   └── ml_strategy.py #   ML 策略 (fetch_data 整合)
│   │   └── utils/
│   │       ├── security.py    #   Docker Secrets 管理
│   │       └── db.py          #   DB config + engine
│   ├── scripts/
│   │   ├── run_daily_screener.py      # 每日選股 CLI
│   │   ├── run_screener_backtest.py   # 選股策略回測
│   │   ├── run_ml_backtest_2024.py    # ML Walk-Forward 回測
│   │   ├── ingest_full_data.py        # 歷史數據入庫
│   │   └── train_local_model.py       # 本地模型訓練 (無 DB)
│   └── tests/
│       ├── test_line_push.py          # LINE 推播測試
│       ├── test_strategies.py         # 策略單元測試
│       ├── test_live_screening.py     # 即時選股測試
│       ├── test_macro_and_sector.py   # 宏觀/產業測試
│       └── test_position_and_risk.py  # 部位/風控測試
├── web/                       # 🌐 Web Dashboard 服務
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── app.py                 # Flask 主應用 (Dashboard + API)
│   ├── db.py                  # DB config + engine + schema helpers
│   ├── security.py            # Docker Secrets 管理
│   ├── bot/
│   │   ├── __init__.py        # Blueprint 導出
│   │   └── handler.py         # Webhook + Top5/ML 命令 + Flex
│   ├── static/                # 靜態資源
│   └── templates/
│       └── index.html         # Dashboard 首頁
├── docker-compose.yml         # 開發環境配置
├── prod.docker-compose.yml    # 生產環境配置
├── requirements.txt           # 全域 Python 依賴
└── README.md                  # 本文件
```

### 模組依賴關係

```
config.py (共用常量/函式)
  ├── strategies/*.py        (calc_rsi, calc_atr, evaluate_stock_rules_v2)
  ├── ml/features.py         (calc_rsi → calculate_rsi 保留向後兼容)
  ├── core/backtest.py       (calc_atr → calculate_atr 保留向後兼容)
  ├── screener/engine.py     (evaluate_stock_rules_v2, Registry 架構)
  └── scripts/*.py           (BACKTEST_SYMBOLS, DEFAULT_SYMBOLS)

strategies/volume_analysis.py (資金流指標)
  ├── ml/features.py         (calc_mfi, calc_cmf, calc_obv)
  └── screener/engine.py     (screen_volume_structure)

adapters/market_data.py
  ├── ml_strategy.py         (fetch_data)
  ├── screener/engine.py     (fetch_data, fetch_fundamentals)
  └── scripts/*.py           (fetch_data, fetch_multiple)

adapters/database.py → utils/db.py → utils/security.py
web/db.py (含 table_exists / column_exists) → web/security.py
```

## 🧪 完整測試指南

### 虛擬環境設置

```powershell
# 建立虛擬環境 (首次)
python -m venv .venv

# 啟動虛擬環境 (Windows PowerShell)
.\.venv\Scripts\Activate.ps1

# 啟動虛擬環境 (Linux/macOS)
source .venv/bin/activate

# 安裝依賴
pip install -r requirements.txt
pip install -r strategies/requirements.txt
pip install -r web/requirements.txt
```

### 1. 語法編譯檢查 (全模組一次檢查)

```powershell
# PowerShell 批次檢查（41 個檔案）
$files = @(
  "strategies/src/config.py", "strategies/src/main.py",
  "strategies/src/utils/__init__.py", "strategies/src/utils/security.py", "strategies/src/utils/db.py",
  "strategies/src/adapters/__init__.py", "strategies/src/adapters/broker.py",
  "strategies/src/adapters/database.py", "strategies/src/adapters/market_data.py",
  "strategies/src/adapters/notifier.py",
  "strategies/src/ml/__init__.py", "strategies/src/ml/features.py", "strategies/src/ml/model.py",
  "strategies/src/core/__init__.py", "strategies/src/core/backtest.py",
  "strategies/src/screener/__init__.py", "strategies/src/screener/engine.py",
  "strategies/src/screener/support_resistance.py",
  "strategies/src/strategies/__init__.py", "strategies/src/strategies/momentum.py",
  "strategies/src/strategies/fundamental.py", "strategies/src/strategies/value.py",
  "strategies/src/strategies/ml_strategy.py", "strategies/src/strategies/institutional.py",
  "strategies/src/strategies/enhanced_momentum.py", "strategies/src/strategies/earnings_quality.py",
  "strategies/src/strategies/volume_analysis.py", "strategies/src/strategies/macro_filter.py",
  "strategies/src/strategies/sector.py", "strategies/src/strategies/registry.py",
  "strategies/scripts/run_daily_screener.py", "strategies/scripts/run_ml_backtest_2024.py",
  "strategies/scripts/run_screener_backtest.py", "strategies/scripts/train_local_model.py",
  "strategies/scripts/ingest_full_data.py", "strategies/train_model.py",
  "web/app.py", "web/db.py", "web/security.py", "web/bot/__init__.py", "web/bot/handler.py"
)
$ok=0; $fail=0
foreach ($f in $files) {
  python -m py_compile $f 2>&1 | Out-Null
  if ($LASTEXITCODE -eq 0) { $ok++ } else { $fail++; Write-Host "FAIL: $f" }
}
Write-Host "py_compile: $ok passed, $fail failed"
```

### 2. 模組導入驗證

```powershell
# 策略引擎全模組
$env:PYTHONPATH="strategies/src"
python -c "
import sys; sys.path.insert(0, 'strategies/src')
from config import calc_rsi, calc_atr, evaluate_stock_rules_v2, DEFAULT_SYMBOLS
from utils.security import get_secret, require_secret, is_production
from utils.db import get_db_config, build_connection_string, get_engine
from ml.features import calculate_rsi, make_features, get_feature_columns
from ml.model import StrategyModel
from strategies.momentum import screen_breakout, screen_acceleration
from strategies.fundamental import screen_peg, screen_dupont
from strategies.volume_analysis import calc_mfi, calc_cmf, calc_obv
from strategies.institutional import screen_institutional
from strategies.enhanced_momentum import screen_multi_tf_momentum, screen_relative_strength
from strategies.earnings_quality import screen_earnings_quality
from strategies.sector import screen_sector_rotation
from strategies.registry import evaluate_all_strategies, calc_composite_score
from core.backtest import calculate_atr
from adapters.market_data import fetch_data, fetch_fundamentals
print('ALL 16 modules imported OK')
"

# Web 模組
python -c "
import sys; sys.path.insert(0, 'web')
from security import get_secret, is_production
from db import get_db_config, get_engine, table_exists, column_exists
print('Web modules OK')
"
```

### 3. 共用函式功能測試 (不需 DB)

```powershell
python -c "
import sys; sys.path.insert(0, 'strategies/src')
import pandas as pd, numpy as np
from config import calc_rsi, calc_atr, calc_rule_score
from strategies.volume_analysis import calc_mfi, calc_cmf

prices = pd.Series([100+i*0.5 for i in range(30)])
print(f'RSI: {calc_rsi(prices).iloc[-1]:.2f}')

df = pd.DataFrame({'High': prices+2, 'Low': prices-2, 'Close': prices})
print(f'ATR: {calc_atr(df).iloc[-1]:.4f}')

score = calc_rule_score(
  {'pass':True,'score':1},{'pass':False,'score':0.6},
  {'pass':True,'score':1},{'pass':False,'score':0.3})
print(f'Rule Score: {score}')

h = pd.Series(np.random.uniform(150,160,30))
l = pd.Series(np.random.uniform(140,150,30))
c = pd.Series(np.random.uniform(145,155,30))
v = pd.Series(np.random.uniform(1e6,5e6,30))
print(f'MFI: {calc_mfi(h,l,c,v).iloc[-1]:.2f}')
print(f'CMF: {calc_cmf(h,l,c,v).iloc[-1]:.4f}')
print('ALL FUNCTION TESTS PASSED')
"
```

### 4. Web API 端點測試 (需啟動 app)

```powershell
# 啟動 Web App
$env:WEB_PORT='6688'
python web/app.py  # 或用 docker-compose up -d

# 測試 API (另開 terminal)
$auth = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes('admin:admin123'))
$h = @{Authorization="Basic $auth"}

Invoke-RestMethod -Uri 'http://localhost:6688/health' -Headers $h
Invoke-RestMethod -Uri 'http://localhost:6688/webhook/info' -Headers $h
Invoke-RestMethod -Uri 'http://localhost:6688/api/recommendations?limit=3' -Headers $h
Invoke-RestMethod -Uri 'http://localhost:6688/api/macro' -Headers $h
Invoke-RestMethod -Uri 'http://localhost:6688/api/sectors' -Headers $h
Invoke-RestMethod -Uri 'http://localhost:6688/api/ml_status' -Headers $h
Invoke-RestMethod -Uri 'http://localhost:6688/api/portfolio' -Headers $h
```

### 5. 每日選股測試

```powershell
# 掃描 5 支股票，輸出 Top 3（不需 DB）
python strategies/scripts/run_daily_screener.py --symbols AAPL,MSFT,NVDA,GOOGL,META --top-n 3

# 掃描並寫入 DB
python strategies/scripts/run_daily_screener.py --save-db --top-n 5
```

### 6. LINE Bot 測試

```powershell
# 推播功能測試
python strategies/tests/test_line_push.py

# Webhook 端點測試
Invoke-RestMethod -Uri 'http://localhost:6688/callback' -Method Post `
  -ContentType 'application/json' -Body '{"events":[]}'
```

## 🔄 服務啟動與關閉

### 開發環境

```bash
# 啟動所有服務
docker-compose up -d

# 查看服務狀態
docker-compose ps

# 查看日誌
docker-compose logs -f                    # 所有服務
docker-compose logs -f strategy_engine    # 策略引擎
docker-compose logs -f web_dashboard      # Web 服務
docker-compose logs -f db                 # 資料庫

# 重啟單一服務
docker-compose restart strategy_engine

# 停止所有服務
docker-compose down

# 停止服務並清除數據卷
docker-compose down -v
```

### 生產環境

```bash
# 啟動
docker-compose -f prod.docker-compose.yml up -d

# 停止
docker-compose -f prod.docker-compose.yml down

# 查看日誌
docker-compose -f prod.docker-compose.yml logs -f
```

### 服務端口

| 服務 | 開發端口 | 生產端口 | 說明 |
|------|---------|---------|------|
| Web Dashboard | 6688 | 6688 | Flask 應用 + LINE Webhook |
| Strategy Engine | 5001 | — | 策略引擎 API (內部) |
| MySQL | 3308 | — (不暴露) | 資料庫 |

### 健康檢查

```bash
# Web Dashboard
curl http://localhost:6688/health

# API 端點
curl http://localhost:6688/api/strategies
curl http://localhost:6688/api/ml_status
curl http://localhost:6688/api/recommendations
```

## 📝 更新日誌

詳見 [doc/updatelist.md](doc/updatelist.md)

## 🔒 安全說明

- 所有敏感資訊使用 Docker Secrets 管理
- 生產環境不暴露資料庫端口
- Line Webhook 使用 HMAC-SHA256 簽名驗證
- Web Dashboard 使用 HTTP Basic Auth 保護

## 📄 授權

MIT License
