# 📋 指令速查表 (QUICK REFERENCE)

日常操作快查。更多詳細指令見 [ADVANCED_REFERENCE.md](ADVANCED_REFERENCE.md)。

---

## 🐳 服務管理

```bash
# 啟動 (開發環境)
docker-compose up -d

# 停止
docker-compose down

# 查看狀態
docker-compose ps

# 查看日誌
docker-compose logs -f                   # 所有服務
docker-compose logs -f web_dashboard     # Web 只
docker-compose logs -f strategy_engine   # 策略引擎

# 重啟單一服務
docker-compose restart web_dashboard
```

---

## 📊 日常操作

```bash
# 運行每日選股 (推薦)
python strategies/scripts/run_daily_screener.py --save-db --notify

# 掃描特定股票 (5 支，輸出 Top 3)
python strategies/scripts/run_daily_screener.py \
  --symbols AAPL,MSFT,NVDA,GOOGL,META --top-n 3

# 完整掃描 (51 支) + ML + 通知
python strategies/scripts/run_daily_screener.py --use-ml true --save-db --notify

# 禁用 ML (純規則)
python strategies/scripts/run_daily_screener.py --use-ml false --save-db
```

---

## 🧪 測試 & 驗證

```bash
# 檢查健康狀態
curl http://localhost:6688/health

# 查詢推薦 (需啟動 Web)
curl -u admin:admin123 \
  'http://localhost:6688/api/recommendations?limit=5'

# LINE Bot Webhook 測試
curl -X POST http://localhost:6688/callback \
  -H "Content-Type: application/json" \
  -d '{"events":[]}'

# 編譯檢查
python -m py_compile strategies/src/config.py
python -m py_compile web/app.py
```

---

## 📚 深度操作

| 需求 | 指令 | 文檔 |
|------|------|------|
| 訓練 ML 模型 | `python strategies/train_local_model.py` | [ADVANCED_REFERENCE.md](ADVANCED_REFERENCE.md#-ml-模型訓練與評估) |
| 回測策略 | `python strategies/scripts/run_screener_backtest.py --months 12` | [ADVANCED_REFERENCE.md](ADVANCED_REFERENCE.md#-walk-forward-回測) |
| API 詳解 | `/api/recommendations`, `/api/ml_status` | [ADVANCED_REFERENCE.md](ADVANCED_REFERENCE.md#-api-端點詳解) |
| 數據庫管理 | `docker-compose exec db mysql -u root -p` | [ADVANCED_REFERENCE.md](ADVANCED_REFERENCE.md#-數據庫操作) |
| 測試套件 | `python -m pytest tests/ -v` | [ADVANCED_REFERENCE.md](ADVANCED_REFERENCE.md#-測試與驗證) |

---

## 🔧 常用環境變數

```bash
# 交易模式
export TRADING_MODE=backtest  # 或 paper, simulation

# 策略類型
export STRATEGY_TYPE=screener # 或 traditional, ml

# 啟用 ML
export USE_ML=true            # 或 false, auto

# Web 服務端口
export WEB_PORT=6688

# 自動調度
export USE_SCHEDULER=true     # 週一~五 16:15 EST 自動運行
```

---

## 🔗 端點速查

| 功能 | 方法 | URL | 認證 |
|------|------|-----|------|
| 健康檢查 | GET | `/health` | — |
| 推薦 | GET | `/api/recommendations?limit=5` | Basic Auth |
| ML 狀態 | GET | `/api/ml_status` | Basic Auth |
| 宏觀數據 | GET | `/api/macro` | Basic Auth |
| 產業排名 | GET | `/api/sectors` | Basic Auth |
| LineBot Webhook | POST | `/callback` | HMAC-SHA256 |

---

## 📖 文檔導航

- **新手入門** → [README.md](README.md)
- **詳細配置** → [QUICK_START.md](QUICK_START.md)
- **LineBot 設置** → [LINEBOT_SETUP.md](LINEBOT_SETUP.md)
- **深度操作** → [ADVANCED_REFERENCE.md](ADVANCED_REFERENCE.md)

