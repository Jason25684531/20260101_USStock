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