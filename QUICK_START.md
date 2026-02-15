# 🚀 詳細配置與故障排除

**快速啟動**: 見 [README.md](README.md#-立即啟動-3-步10-分鐘)

本文檔涵蓋詳細的配置步驟和常見問題解決方案。

---

## 配置詳解

### Secrets 文件詳細說明

每個 `.secrets/` 文件應包含對應的值，無額外空格或換行符。

| 文件 | 內容 | 來源 | 範例 |
|------|------|------|------|
| `db_root_password.txt` | MySQL root 密碼 | 自選 | `MySecurePassword123!` |
| `db_password.txt` | DB 應用程式密碼 | 自選 | `AppPassword456!` |
| `alpaca_key.txt` | Alpaca API Key | [alpaca.markets](https://alpaca.markets/) | `PK...` |
| `alpaca_secret.txt` | Alpaca API Secret | [alpaca.markets](https://alpaca.markets/) | `...` |
| `line_channel_token.txt` | Line Channel Token | [Line Developers](https://developers.line.biz/) | `Channel...` |
| `line_channel_secret.txt` | Line Channel Secret | [Line Developers](https://developers.line.biz/) | `Secret...` |
| `line_user_id.txt` | 你的 Line User ID | 見 LineBot 設置章節 | `Uxxx...` |

**⚠️ 檢查 Secrets 內容**:

```bash
# 驗證無多餘空格或換行
cat .secrets/db_password.txt | od -c
# 輸出應只包含 ASCII 字符與最多一個換行

# 或用 wc -c 檢查字符數
wc -c .secrets/db_password.txt
# 應 < 100 字符
```

### Alpaca 帳號設置

1. 前往 https://alpaca.markets/
2. 點擊「Sign Up」並完成註冊（免費）
3. 驗證郵箱
4. 登入後進入「Account Settings」
5. 在「API Keys」找到：
   - **API Key** → 複製至 `.secrets/alpaca_key.txt`
   - **API Secret** → 複製至 `.secrets/alpaca_secret.txt`
6. ⚠️ 確保 **Paper Trading** 模式已啟用（默認啟用）

### Line Developers 帳號設置

見完整指南 [LINEBOT_SETUP.md](LINEBOT_SETUP.md) 的 「第 1-3 步」。

---

## 故障排除 (Troubleshooting)

### Q1: Docker 無法啟動或 Port 已被使用

**症狀**: `docker-compose up -d` 返回錯誤

```bash
# 檢查端口佔用
lsof -i :6688      # Linux/macOS
netstat -ano | findstr :6688  # Windows

# 如果已被使用，修改 docker-compose.yml
# "6688:5000" 改為 "6689:5000"
nano docker-compose.yml

# 重啟服務
docker-compose down
docker-compose up -d
```

### Q2: MySQL 連接失敗 (Connection Refused)

**症狀**: `ERROR 2003 (HY000): Can't connect to MySQL server`

```bash
# 檢查 DB 容器是否運行
docker-compose ps | grep db

# 如果未運行，查看日誌
docker-compose logs db

# 確認 Secrets 文件無多餘空格
hexdump -C .secrets/db_password.txt

# 強制重新啟動 DB
docker-compose restart db
sleep 30  # 等待數據庫初始化
```

**常見原因**：
- `.secrets/db_password.txt` 含多餘空格或換行符
- DB 容器未完全啟動（需等待 30 秒）
- 防火牆阻止連接

### Q3: Web Dashboard 無法訪問 (Connection Refused)

**症狀**: `curl http://localhost:6688/health` 失敗

```bash
# 檢查 web_dashboard 容器
docker-compose ps | grep web

# 查看 Web 容器日誌
docker-compose logs web_dashboard | tail -50

# 檢查網絡連接
docker network ls
docker network inspect `docker network ls -q | head -1`

# 確認 Flask 綁定配置
# 檢查是否監聽 0.0.0.0:5000（而非 127.0.0.1)
```

**常見原因**：
- 容器未成功啟動（查看日誌中的 Python 錯誤）
- 績效問題導致啟動緩慢
- 環境變數設置錯誤

### Q4: 驗證失敗 (Authentication Failed)

**症狀**: 登入 Web Dashboard 時「Invalid credentials」

```bash
# 預設憑證
用戶名: admin
密碼: admin123

# 重新檢查這些是否被修改過
# 如需修改，見 web/app.py 中的 @app.before_request 區段

# 清除瀏覽器快取和 Cookies
# 設置 → 隱私與安全 → 清除快取
```

### Q5: LineBot Webhook 驗證失敗

**症狀**: Line Developers 顯示「Verify Failed」

```bash
# 檢查 Ngrok 是否運行且 URL 有效
# 在瀏覽器中直接訪問: https://xxxxx-xxx.ngrok-free.app/health

# 測試 Webhook 端點
curl -X POST https://xxxxx-xxx.ngrok-free.app/callback \
  -H "Content-Type: application/json" \
  -d '{"events":[]}'
# 應返回 200 OK

# 檢查 Web 服務日誌
docker-compose logs web_dashboard | grep -i webhook

# 驗證 Channel Secret 是否正確
cat .secrets/line_channel_secret.txt
```

**常見原因**：
- Ngrok 連接已斷開（需重啟 Ngrok）
- Channel Secret 不匹配
- Webhook URL 未保存到 Line Console

### Q6: API 認證失敗 (401 Unauthorized)

**症狀**: curl 返回 `401 Unauthorized`

```bash
# 檢查認證令牌是否正確
pair="admin:admin123"
token=$(echo -n "$pair" | base64)
echo $token

# 在 curl 中使用
curl -H "Authorization: Basic $token" \
  http://localhost:6688/api/recommendations

# 或使用 -u 參數
curl -u admin:admin123 \
  http://localhost:6688/api/recommendations
```

### Q7: 運行 Python 腳本時 ImportError

**症狀**: `ModuleNotFoundError: No module named 'strategies'`

```bash
# 檢查虛擬環境是否啟動
which python  # 應指向 .venv/bin/python

# 或 Windows
python.exe -V

# 啟動虛擬環境
source .venv/bin/activate  # Linux/macOS
.\.venv\Scripts\Activate.ps1  # Windows PowerShell

# 重新安裝依賴
pip install -r requirements.txt
pip install -r strategies/requirements.txt
```

### Q8: Docker 內存不足

**症狀**: 容器突然停止，日誌顯示 OOM

```bash
# 檢查 Docker 資源限制
docker stats

# 調整 docker-compose.yml 中的資源限制
services:
  web_dashboard:
    mem_limit: 512m      # 限制為 512MB
  strategy_engine:
    mem_limit: 1024m     # 限制為 1GB
  db:
    mem_limit: 1024m     # 限制為 1GB

# 清理 Docker 系統資源
docker system prune -a
docker volume prune
```

---

## 進階檢查

### 驗證完整系統健康狀態

```bash
# 執行完整健康檢查
docker-compose exec web_dashboard curl -s http://localhost:5000/health | jq .

# 檢查 API 端點
docker-compose exec web_dashboard curl -u admin:admin123 \
  http://localhost:5000/api/recommendations | jq . | head -20

# 檢查 DB 連接
docker-compose exec web_dashboard python -c \
  "from db import get_engine; engine = get_engine(); print('DB OK')"
```

### 查看系統版本信息

```bash
# Python 版本
python --version

# Docker 版本
docker --version
docker-compose --version

# MySQL 版本
docker-compose exec db mysql -u root -p -e "SELECT VERSION();"

# 檢查 Python 依賴
pip list | grep -E "pandas|numpy|xgboost|flask"
```

---

## 性能優化

### 加速 Docker 啟動

```bash
# 預建映像（而非每次啟動都重建）
docker-compose build
docker-compose up -d

# 使用本地數據卷進行持久化
# 編輯 docker-compose.yml，確保有 volumes:
services:
  db:
    volumes:
      - mysql_data:/var/lib/mysql

volumes:
  mysql_data:
```

### 優化 ML 訓練速度

```bash
# 使用 GPU 加速（若可用）
# 在訓練時設置 GPU 參數
# (需確保 Docker 支持 GPU，見 docker-compose.yml 的 runtime: nvidia)
```

---

## 文檔導航

- **核心啟動** → [README.md](README.md#-立即啟動-3-步10-分鐘)
- **LineBot 設置** → [LINEBOT_SETUP.md](LINEBOT_SETUP.md)
- **常用指令** → [COMMANDS_REFERENCE.md](COMMANDS_REFERENCE.md)
- **深度操作** → [ADVANCED_REFERENCE.md](ADVANCED_REFERENCE.md)

---

**還是有問題?** 檢查 Docker 日誌或在 GitHub Issues 提報。
