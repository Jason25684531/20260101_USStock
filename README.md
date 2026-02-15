# USStock - 美股量化交易系統

## 簡介
- 策略引擎：量化篩選、回測、排程與信號產出
- Web Dashboard：API 與視覺化儀表板
- LineBot：指令互動與訊號推播
- MySQL：市場資料與回測結果持久化

## 架構與服務
| 服務 | 說明 | 對外連接埠 |
| --- | --- | --- |
| `db` | MySQL 8 | `3308 -> 3306` |
| `strategy_engine` | 策略/回測/排程 | `5001 -> 5000` |
| `web_dashboard` | API + LineBot + Dashboard | `6688 -> 6688` |

## 目錄結構
- `strategies/` 策略引擎與回測邏輯
- `web/` Web Dashboard 與 LineBot 介面
- `database/` MySQL 初始化與設定
- `scripts/` 作業腳本與維運工具
- `doc/` 文件與變更紀錄
- `data/` 回測/報表輸出

## 快速啟動 (Docker)
1. 準備設定檔
請先確認 `.env` 與 Docker Secrets 設定，細節可參考 `QUICK_START.md`。
```
mkdir .secrets
```
2. 啟動服務
```
docker-compose up -d
```
3. 健康檢查
```
curl http://localhost:6688/health
```

## 啟動/關閉/狀態
- 啟動：`docker-compose up -d`
- 停止：`docker-compose stop`
- 關閉並移除容器：`docker-compose down`
- 查詢狀態：`docker-compose ps`
- 查看日誌：`docker-compose logs -f web_dashboard`

## 本機開發 (虛擬環境)
```
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```
- 策略引擎：`python strategies/src/main.py`
- Web Dashboard：`python web/app.py`

## 測試
### 單元測試 (策略)
```
python -m pytest strategies/tests
```

### 全功能回歸 (需 Docker 服務已啟動)
```
.\verify_all.ps1
```

### LineBot 檢查 (需 Web Dashboard 已啟動)
```
.\test_linebot.ps1
```

### 手動檢核腳本
```
python strategies/scripts/manual_checks/live_screening.py
python strategies/scripts/manual_checks/line_push.py --handler
python strategies/scripts/manual_checks/line_push.py --db
python strategies/scripts/manual_checks/line_push.py --send
```

## 相關文件
- `QUICK_START.md`
- `COMMANDS_REFERENCE.md`
- `ADVANCED_REFERENCE.md`
- `LINEBOT_SETUP.md`
- `LINEBOT_TROUBLESHOOTING.md`
- `doc/updatelist.md`
