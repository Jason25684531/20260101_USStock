# USStock - 美股量化交易系統

## 專案概覽
- 策略引擎：量化篩選、回測、排程與訊號產出
- Web Dashboard：API 與視覺化儀表板
- LineBot：指令互動與訊號推播
- MySQL：市場資料與回測結果持久化

## 全端架構與服務
| 服務 | 說明 | 對外連接埠 | 容器內埠 |
| --- | --- | --- | --- |
| `db` | MySQL 8 | `3308` | `3306` |
| `strategy_engine` | 策略/回測/排程 | `5001` | `5000` |
| `web_dashboard` | API + LineBot + Dashboard | `6688` | `5000` |

## 架構流程（資料流）
1. `strategy_engine` 讀取市場資料與基本面資料，產生策略訊號與回測結果
2. `db` 儲存 market_data / trade_logs / backtest_runs / recommendations 等表
3. `web_dashboard` 透過 API 查詢 DB，提供 Dashboard 與 LineBot 回覆
4. LineBot 由 Webhook `/callback` 接收事件並回應4

## 資料夾結構
- `strategies/` 策略引擎與回測邏輯
- `web/` Web Dashboard 與 LineBot 介面
- `database/` MySQL 初始化與設定
- `scripts/` 作業腳本與維運工具
- `doc/` 文件與變更紀錄
- `data/` 回測/報表輸出

## 全端啟動 (Docker)
1. 準備設定檔  
確認 `.env` 與 Docker Secrets 設定，細節請參考 `QUICK_START.md`。
```
mkdir .secrets
```
2. 啟動服務
```
docker-compose up -d
docker-compose ps
```
3. 健康檢查
```
Invoke-RestMethod -Uri 'http://127.0.0.1:6688/health' -Method Get
```
4. Dashboard  
URL：`http://127.0.0.1:6688`  
預設帳密：`admin` / `admin123`

## 全端關閉/重啟
- 啟動：`docker-compose up -d`
- 停止：`docker-compose stop`
- 關閉並移除容器：`docker-compose down`
- 重啟單一服務：`docker-compose restart web_dashboard`
- 重建並啟動：`docker-compose up -d --build`
- 查看日誌：`docker-compose logs -f web_dashboard`

## 本機開發 (虛擬環境)
```
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```
- 策略引擎：`python strategies/src/main.py`
- Web Dashboard：`python web/app.py`  
  預設埠號：`6688`（可用 `WEB_PORT` 調整）

## 網頁前端（Web Dashboard）
### 主要檔案
- 前端模板：`web/templates/index.html`
- 前端樣式：`web/static/style.css`
- 後端 API：`web/app.py`
- LineBot 指令：`web/bot/handler.py`

### 啟動與關閉
- Docker 啟動：`docker-compose up -d web_dashboard`
- Docker 停止：`docker-compose stop web_dashboard`
- Docker 重啟：`docker-compose restart web_dashboard`
- 本機啟動：`python web/app.py`

### 前端檢查
- Dashboard：`http://127.0.0.1:6688`
- 健康檢查：`http://127.0.0.1:6688/health`
- LineBot Webhook：`http://127.0.0.1:6688/webhook/info`

## Python 回測與訓練指令
### 選股策略 Walk-Forward 回測
```
python strategies/scripts/run_screener_backtest.py
python strategies/scripts/run_screener_backtest.py --symbols AAPL,MSFT,NVDA,GOOGL,META --months 12 --top-n 5 --fee 0.001
```

### ML Walk-Forward 回測
```
python strategies/scripts/run_ml_backtest_2024.py --symbol AAPL --start 2024-01-01 --buy-threshold 0.55 --sell-threshold 0.3
python strategies/scripts/run_ml_backtest_2024.py --symbol AAPL --model data/model.pkl
```

### 本機 ML 訓練 (yfinance)
```
python strategies/scripts/train_local_model.py
```

### DB 版 ML 訓練 (需資料庫已備齊)
```
python strategies/train_model.py
```

## 測試與驗證
### 單元測試 (策略)
```
python -m pytest strategies/tests
```

### 全流程回歸 (需 Docker 服務已啟動)
```
.\verify_all.ps1
```

### LineBot 檢查 (需 Web Dashboard 已啟動)
```
.\test_linebot.ps1
```
`/callback POST` 會因缺少 `X-Line-Signature` 回 400，屬於預期安全行為。

### 手動檢核腳本
```
python strategies/scripts/manual_checks/live_screening.py
python strategies/scripts/manual_checks/line_push.py --handler
python strategies/scripts/manual_checks/line_push.py --db
python strategies/scripts/manual_checks/line_push.py --send
```

## 除錯與排查
- 服務狀態：`docker-compose ps`
- Web 健康：`http://127.0.0.1:6688/health`
- LineBot Webhook：`http://127.0.0.1:6688/webhook/info`
- Web 日誌：`docker-compose logs -f web_dashboard`
- 資料庫連線：確認 `db` 服務為 healthy，且 `.env`/secrets 正確
- API 端點：`/api/recommendations`、`/api/strategies`、`/api/macro`、`/api/sectors`

## LineBot 指令
| 指令 | 說明 |
| --- | --- |
| `Top5` | 今日選股推薦（含 ML） |
| `Top5基礎` | 純規則推薦（不含 ML） |
| `ML AAPL` | 個股 ML 分析 |
| `/stock AAPL` | 個股詳細分析 |
| `/market` | 宏觀環境 |
| `/history 0214` | 歷史推薦 |
| `/sector` | 產業動能排行 |
| `/status` | 系統狀態 |
| `/help` | 指令說明 |
| `/strategies` | 策略列表與提示 |

## 相關文件
- `QUICK_START.md`
- `COMMANDS_REFERENCE.md`
- `ADVANCED_REFERENCE.md`
- `LINEBOT_SETUP.md`
- `LINEBOT_TROUBLESHOOTING.md`
- `doc/updatelist.md`
d

## 系統架構與操作指南

### 架構總覽

本專案以 Docker Compose 啟動三個主要服務：

| 服務 | 職責 | 對外連線 |
| --- | --- | --- |
| `db` | MySQL 8，保存市場資料、每日推薦、回測、交易與 provider health log | `localhost:3308` -> container `3306` |
| `strategy_engine` | 執行每日選股、資料拉取、ML/策略計算、排程與 Line 主動推播 | container `5000`，本機 `5001` |
| `web_dashboard` | Flask Dashboard、API、LineBot webhook 與查詢指令 | `http://127.0.0.1:6688` |

資料流如下：

1. `strategy_engine` 透過 provider chain 拉取行情與基本資料，寫入 MySQL。
2. 每日選股流程產生 `daily_recommendations`，這是 Dashboard、LineBot 指令與每日早晨推播的共同資料來源。
3. `web_dashboard` 只負責查詢、呈現與 webhook 回覆，不應重新計算排名。
4. LineBot command Top5 與每日早晨推播共用 `utils/line_flex.py` 的 canonical recommendation Flex builder，避免同一批推薦資料出現不同卡片格式。
5. LineBot 讀取 MySQL 時使用短連線 scope、pool pre-ping 與 stale connection retry；若 MySQL 仍不可用，會回覆安全訊息，不暴露 SQL 或 stack trace。

### 重要檔案說明

| 路徑 | 說明 |
| --- | --- |
| `docker-compose.yml` | 本機 Docker Compose 服務定義：MySQL、策略引擎、Web Dashboard |
| `.env` | 本機環境變數與 API/LINE/DB 設定；不要提交真實 secrets |
| `utils/db.py` | 共用 DB connection string 與 SQLAlchemy engine 建立；包含 pool health checks |
| `utils/line_flex.py` | Web 與 strategy 共用的 LINE Flex 格式化、sanitization、推薦卡片 builder |
| `web/app.py` | Flask Dashboard 與 API endpoint |
| `web/bot/handler.py` | LineBot webhook、指令路由、DB 查詢與回覆組裝 |
| `web/bot/flex_messages.py` | LineBot read-only command 的輔助 Flex builders |
| `strategies/src/main.py` | strategy runtime 入口；`USE_SCHEDULER=true` 時啟動排程 |
| `strategies/src/adapters/notifier.py` | LINE 主動推播 adapter；每日推播使用共用推薦卡片 builder |
| `strategies/scripts/run_daily_screener.py` | 手動執行每日選股、寫入 DB、推播 |
| `scripts/pull_market_data.py` | 手動拉取指定股票行情資料並記錄拉取狀態 |
| `database/init/` | MySQL 初始化 schema |
| `docs/ops_runtime.md` | 更詳細的 runtime、scheduler、data pull 與故障排查文件 |

### 啟動、關閉與重啟

```powershell
# 啟動全部服務
docker compose up -d

# 查看服務狀態
docker compose ps

# 查看主要服務 logs
docker compose logs -f web_dashboard
docker compose logs -f strategy_engine
docker compose logs -f db

# 只重啟 Web Dashboard / LineBot
docker compose restart web_dashboard

# 只重啟策略引擎與排程
docker compose restart strategy_engine

# 停止但保留 container 與 volume
docker compose stop

# 停止並移除 container，保留 named volume 資料
docker compose down

# 重建 image 後啟動
docker compose up -d --build
```

Dashboard health check：

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:6688/health" -Method Get
```

### 資料拉取與每日推薦

手動拉取市場資料：

```powershell
# 實際寫入 market_data / pull log
python scripts/pull_market_data.py --symbols AAPL,MSFT,NVDA

# dry-run，只檢查 provider 與流程，不寫入
python scripts/pull_market_data.py --symbols AAPL,MSFT,NVDA --dry-run
```

手動執行每日選股：

```powershell
# 掃描、計算推薦並寫入 daily_recommendations
python strategies/scripts/run_daily_screener.py --save-db

# 指定股票與 Top N
python strategies/scripts/run_daily_screener.py --symbols AAPL,MSFT,NVDA --top-n 5 --use-ml --save-db

# 寫入 DB 後推播 LINE Flex card
python strategies/scripts/run_daily_screener.py --save-db --notify
```

排程模式由 `strategy_engine` 負責。Docker Compose 預設：

```env
USE_SCHEDULER=true
STRATEGY_TYPE=screener
SCREENER_TOP_N=5
SCHEDULER_HOUR=16
SCHEDULER_MINUTE=15
TZ=America/New_York
```

每日早晨推播與 LineBot `top5` / `/recommendations` 顯示同一種推薦卡片格式；若卡片要改版，優先修改 `utils/line_flex.py` 的共用 builder。

## Production Runtime Notes

### Scheduled screener mode

Use the strategy engine scheduler as the official `daily_recommendations` writer.

- `USE_SCHEDULER=true`
- `STRATEGY_TYPE=screener`
- `SCREENER_TOP_N=5`
- `SCHEDULER_HOUR=16`
- `SCHEDULER_MINUTE=15`

This keeps the dashboard and LINE recommendation consumers aligned on the latest `scan_date`.

### Unified model path

Set `MODEL_PATH=/app/data/model.pkl` for every service that reads or writes model artifacts.

- `strategy_engine` reads and writes the primary model path through the shared resolver
- `DailyScreener` auto-detects ML availability from the same resolver
- `web_dashboard /api/ml_status` reads the same effective path
- Docker services that need model access should mount `./data:/app/data`

`TEST_MODEL_PATH` is reserved for explicit local or test fallback only.

### Database credential model

Application services should default to `DB_USER=trader`.

- `DB_USER=root` uses `DB_ROOT_PASSWORD` or the `db_root_password` secret
- non-root app users use `DB_PASSWORD` or the `db_password` secret
- root credentials are reserved for MySQL initialization, admin tasks, and DB healthchecks

The current `.env` secret hygiene should be reviewed separately; this operational risk is documented but not remediated by this change.

### Trading modes

- `TRADING_MODE=backtest`: generate signals only, do not submit broker orders
- `TRADING_MODE=paper`: execute through `AlpacaBroker` paper trading
- `TRADING_MODE=simulation`: execute locally through `MockBroker` only

Simulation mode must never call Alpaca or any real broker API. Notifications and logs should label these executions as `Simulation Trading`.

### Web healthcheck

Production healthchecks should use Python stdlib `urllib` against `http://localhost:6688/health` so the image does not require `curl`.
