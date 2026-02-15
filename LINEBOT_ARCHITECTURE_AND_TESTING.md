# LINE Bot 系統架構觀察 & 測試完整指南

## 🏗️ 當前系統架構

```
┌─────────────────────────────────────────────────────────────────────┐
│                    美股量化交易 LINE Bot 系統                         │
└─────────────────────────────────────────────────────────────────────┘

1️⃣ 核心服務層
   ┌──────────────────────────────────────────────────────────────┐
   │  Flask Web Dashboard (host: 0.0.0.0, port: 6688)             │
   │  ├─ 文件: web/app.py                                          │
   │  ├─ 路由: / (首頁), /api/*, /callback (Webhook)              │
   │  └─ 認證: HTTPBasicAuth (admin/admin123)                     │
   └──────────────────────────────────────────────────────────────┘

2️⃣ LINE Bot 處理層
   ┌──────────────────────────────────────────────────────────────┐
   │  LINE Bot Blueprint (web/bot/)                                │
   │  ├─ 文件: web/bot/handler.py (983 行)                         │
   │  ├─ 簽名驗證: @verify_signature (HMAC-SHA256)                │
   │  ├─ Webhook 端點: POST /callback                              │
   │  ├─ 健康檢查: GET /callback, GET /webhook/info               │
   │  └─ 命令處理: help, Top5, /stock, /market 等                 │
   └──────────────────────────────────────────────────────────────┘

3️⃣ 數據層
   ┌──────────────────────────────────────────────────────────────┐
   │  MySQL Database (localhost:3308, port: 3308)                 │
   │  ├─ 表: market_data, daily_recommendations                   │
   │  ├─ 表: backtest_runs, equity_curve, trade_logs              │
   │  ├─ 表: sector_momentum, macro_data                          │
   │  └─ 備註: 當前未運行，不影響 Webhook 驗證                     │
   └──────────────────────────────────────────────────────────────┘

4️⃣ 外部連接層
   ┌──────────────────────────────────────────────────────────────┐
   │  ngrok 隧道 (用於 LINE 穿透)                                   │
   │  ├─ 本地: http://127.0.0.1:6688                               │
   │  ├─ 公網: https://your-ngrok-url.ngrok.io                    │
   │  └─ 狀況: 已驗證單進程運行，HTTP 響應完整 ✅                   │
   └──────────────────────────────────────────────────────────────┘

5️⃣ LINE Platform 側
   ┌──────────────────────────────────────────────────────────────┐
   │  LINE Messaging API                                          │
   │  ├─ Channel Token: TGQXVjNIF7h4xoDRh+5JJZla... (已配置)      │
   │  ├─ Channel Secret: bbe0bb916e87ac5b42e775e9b6b4f038        │
   │  ├─ Webhook URL: https://your-ngrok-url/callback             │
   │  └─ 簽名驗證: HMAC-SHA256 (X-Line-Signature header)          │
   └──────────────────────────────────────────────────────────────┘
```

---

## 📋 系統流程圖

```
┌─────────────────────────────────────────────────────────────────┐
│                      用戶與 LINE Bot 互動流程                      │
└─────────────────────────────────────────────────────────────────┘

用戶在 LINE 中操作
          ↓
    發送文字訊息
          ↓
    LINE Platform
          ↓
    通過 ngrok 隧道
          ↓
    Flask Webhook: POST /callback
          ↓
    驗證簽名 (HMAC-SHA256)
          ├─ 有效 ✅ → 繼續
          └─ 無效 ❌ → 返回 403 Forbidden
          ↓
    解析事件類型
          ├─ message (文字訊息)
          ├─ follow (新用戶關注)
          └─ unfollow (用戶取消關注)
          ↓
    執行命令處理
          ├─ Top5 → _cmd_top5()
          ├─ /stock AAPL → _cmd_stock()
          ├─ /market → _cmd_market()
          ├─ help → 命令列表
          └─ ... (其他命令)
          ↓
    查詢數據庫 (如需要)
          ├─ daily_recommendations
          ├─ sector_momentum
          ├─ macro_data
          └─ ... (其他表)
          ↓
    組建回應訊息
          ├─ 文字訊息 (Text)
          ├─ Flex Message (卡片)
          └─ 多個訊息組合
          ↓
    通過 reply_messages() 回復
          ↓
    LINE Platform
          ↓
    推送給用戶
          ↓
    用戶在 LINE 中看到回應
```

---

## 🧪 LINE Bot 完整測試指南

### 📌 前置條件

```powershell
# 1. 確保 Flask 單獨運行（只有一個進程監聽 6688）
netstat -ano | findstr ':6688.*LISTENING'
# 應該只有一行結果

# 2. 確認當前目錄
cd D:\01_Project\20260101_USStock

# 3. 確認虛擬環境已激活
.venv\Scripts\Activate.ps1
```

---

### 🔹 第一層測試：本地端點測試（無 ngrok）

#### 1.1 基本健康檢查

```powershell
# 測試 Flask 是否運行
$response = Invoke-RestMethod -Uri 'http://127.0.0.1:6688/health' -Method Get
$response | ConvertTo-Json
```

**預期結果：**
```json
{
  "status": "healthy",
  "timestamp": "2026-02-15T22:57:42",
  "database": "connected" (或 "disconnected")
}
```

#### 1.2 測試 Webhook 端點 (GET)

```powershell
# LINE 會先發送 GET 請求驗證端點
$response = Invoke-RestMethod -Uri 'http://127.0.0.1:6688/callback' -Method Get
$response | ConvertTo-Json
```

**預期結果：**
```json
{
  "status": "ok",
  "message": "LINE Bot Webhook is running",
  "endpoint": "/callback",
  "methods": ["GET", "POST"]
}
```

#### 1.3 測試 Webhook 信息

```powershell
# 查看 Channel Secret & Token 配置
$response = Invoke-RestMethod -Uri 'http://127.0.0.1:6688/webhook/info' -Method Get
$response | ConvertTo-Json
```

**預期結果：**
```json
{
  "status": "active",
  "endpoint": "/callback",
  "channel_secret_configured": true,
  "channel_token_configured": true
}
```

#### 1.4 測試簽名驗證 (POST 無簽名 - 應該失敗)

```powershell
# 這應該返回 400 或 403（預期行為）
try {
    $body = @{events = @()} | ConvertTo-Json
    $response = Invoke-RestMethod -Uri 'http://127.0.0.1:6688/callback' `
        -Method Post `
        -ContentType 'application/json' `
        -Body $body
    Write-Host "⚠️ 意外成功（簽名驗證失敗）" -ForegroundColor Yellow
} catch {
    Write-Host "✅ 正確拒絕無簽名請求: $($_.Exception.Response.StatusCode)" -ForegroundColor Green
}
```

**預期結果：**
- 返回 400 Bad Request (缺少簽名標頭)
- 或 403 Forbidden (簽名驗證失敗)

---

### 🔹 第二層測試：簽名驗證測試（本地）

#### 2.1 生成正確的簽名

```powershell
# 準備測試數據
$body = '{"events":[]}'
$secret = 'bbe0bb916e87ac5b42e775e9b6b4f038'

# 計算 HMAC-SHA256
$hmac = New-Object System.Security.Cryptography.HMACSHA256
$hmac.Key = [System.Text.Encoding]::UTF8.GetBytes($secret)
$hash = $hmac.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($body))
$signature = [Convert]::ToBase64String($hash)

Write-Host "生成的簽名: $signature"
```

#### 2.2 使用正確簽名發送請求

```powershell
# 使用上面生成的簽名
$headers = @{
    'X-Line-Signature' = $signature
    'Content-Type' = 'application/json'
}

try {
    $response = Invoke-RestMethod -Uri 'http://127.0.0.1:6688/callback' `
        -Method Post `
        -Headers $headers `
        -Body $body
    
    Write-Host "✅ 簽名驗證成功！" -ForegroundColor Green
    $response | ConvertTo-Json
} catch {
    Write-Host "❌ 簽名驗證失敗: $($_)" -ForegroundColor Red
}
```

**預期結果：**
```json
{
  "status": "ok"
}
```

---

### 🔹 第三層測試：模擬 LINE 事件測試

#### 3.1 模擬「文字訊息」事件

```powershell
# 準備事件數據
$timestamp = [System.DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
$eventJson = @{
    events = @(
        @{
            type = "message"
            message = @{
                type = "text"
                id = "100001"
                text = "help"
            }
            replyToken = "nHuyWiB7yP5Zw52FIkcQT"  # 測試 token
            source = @{
                type = "user"
                userId = "Utest123456789abcdef"
            }
            timestamp = $timestamp
        }
    )
} | ConvertTo-Json -Depth 10

# 計算簽名
$secret = 'bbe0bb916e87ac5b42e775e9b6b4f038'
$hmac = New-Object System.Security.Cryptography.HMACSHA256
$hmac.Key = [System.Text.Encoding]::UTF8.GetBytes($secret)
$hash = $hmac.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($eventJson))
$signature = [Convert]::ToBase64String($hash)

# 發送請求
$headers = @{
    'X-Line-Signature' = $signature
    'Content-Type' = 'application/json'
}

Write-Host "📨 發送 help 命令..." -ForegroundColor Cyan
try {
    $response = Invoke-RestMethod -Uri 'http://127.0.0.1:6688/callback' `
        -Method Post `
        -Headers $headers `
        -Body $eventJson
    
    Write-Host "✅ 事件已發送，Flask 應該開始處理命令" -ForegroundColor Green
    Write-Host "   查看 Flask 終端的日誌輸出..." -ForegroundColor Gray
} catch {
    Write-Host "❌ 發送失敗: $($_)" -ForegroundColor Red
}
```

**檢查 Flask 終端應該看到：**
```
📨 收到 1 個事件
🔔 處理事件類型: message
✅ 簽名驗證成功
📩 收到文字消息: 'help' from Utest123456789abc
```

#### 3.2 模擬「關注」事件

```powershell
# 準備 follow 事件
$eventJson = @{
    events = @(
        @{
            type = "follow"
            replyToken = "nHuyWiB7yP5Zw52FIkcQT"
            source = @{
                type = "user"
                userId = "Utest987654321xyz"
            }
            timestamp = [System.DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
        }
    )
} | ConvertTo-Json -Depth 10

# 計算簽名並發送
$secret = 'bbe0bb916e87ac5b42e775e9b6b4f038'
$hmac = New-Object System.Security.Cryptography.HMACSHA256
$hmac.Key = [System.Text.Encoding]::UTF8.GetBytes($secret)
$hash = $hmac.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($eventJson))
$signature = [Convert]::ToBase64String($hash)

$headers = @{
    'X-Line-Signature' = $signature
    'Content-Type' = 'application/json'
}

Write-Host "👋 發送 follow 事件..." -ForegroundColor Cyan
Invoke-RestMethod -Uri 'http://127.0.0.1:6688/callback' `
    -Method Post `
    -Headers $headers `
    -Body $eventJson
```

---

### 🔹 第四層測試：ngrok 穿透測試

#### 4.1 啟動 ngrok

```powershell
# 新開一個終端

# 確保在項目根目錄
cd D:\01_Project\20260101_USStock

# 啟動 ngrok（必須是 6688）
.\ngrok.exe http 6688
```

**看到這樣的輸出：**
```
Session Status                online
Forwarding                    https://abc1234-xyz56789.ngrok.io -> http://localhost:6688
Region                        us
Web Interface                 http://127.0.0.1:4040
```

**重要：記下 HTTPS URL，例如 `https://abc1234-xyz56789.ngrok.io`**

#### 4.2 測試 ngrok 連接

```powershell
# 在另一個終端測試
$ngrokUrl = "https://abc1234-xyz56789.ngrok.io"  # 替換為你的 URL

# 測試 GET 請求
Write-Host "測試 ngrok 連接..." -ForegroundColor Cyan
try {
    $response = Invoke-RestMethod -Uri "$ngrokUrl/callback" -Method Get
    Write-Host "✅ ngrok 連接成功！" -ForegroundColor Green
    $response | ConvertTo-Json
} catch {
    Write-Host "❌ ngrok 連接失敗: $($_)" -ForegroundColor Red
}
```

**預期結果：**
```json
{
  "status": "ok",
  "message": "LINE Bot Webhook is running",
  "endpoint": "/callback",
  "methods": ["GET", "POST"]
}
```

#### 4.3 測試 ngrok 上的簽名驗證

```powershell
$ngrokUrl = "https://abc1234-xyz56789.ngrok.io"

# 準備事件和簽名
$body = '{"events":[]}'
$secret = 'bbe0bb916e87ac5b42e775e9b6b4f038'

$hmac = New-Object System.Security.Cryptography.HMACSHA256
$hmac.Key = [System.Text.Encoding]::UTF8.GetBytes($secret)
$hash = $hmac.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($body))
$signature = [Convert]::ToBase64String($hash)

$headers = @{
    'X-Line-Signature' = $signature
    'Content-Type' = 'application/json'
}

Write-Host "📨 通過 ngrok 發送帶簽名的請求..." -ForegroundColor Cyan
try {
    $response = Invoke-RestMethod -Uri "$ngrokUrl/callback" `
        -Method Post `
        -Headers $headers `
        -Body $body `
        -UseBasicParsing
    
    Write-Host "✅ ngrok 簽名驗證成功！" -ForegroundColor Green
    $response | ConvertTo-Json
} catch {
    Write-Host "❌ 失敗: $($_)" -ForegroundColor Red
}
```

---

### 🔹 第五層測試：LINE Developer Console 驗證

#### 5.1 更新 Webhook URL

1. 前往 [LINE Developers Console](https://developers.line.biz/console/)
2. 選擇你的 Messaging API Channel
3. 進入「Messaging API」設定頁面
4. 找到「Webhook 設定」區塊
5. 将 Webhook URL 改為：`https://abc1234-xyz56789.ngrok.io/callback`
   - 替換 `abc1234-xyz56789` 為你的實際 ngrok URL
6. 確保「Webhook 使用」是打開的 ✅

#### 5.2 驗証 Webhook URL

1. 在同一頁面，找到「驗証」按鈕
2. 點擊「驗証」

**✅ 成功的情況：**
- 顯示綠色勾勾 ✓
- 訊息：「Webhook URL 驗証成功」

**❌ 失敗的情況：**
- 顯示紅色叉叉 ✗
- 錯誤代碼：
  | 代碼 | 原因 | 解決 |
  |------|------|------|
  | 503 | Flask 沒運行或端口不對 | 確認 Flask 在 6688 執行 |
  | 504 | 超時 | ngrok 連接中斷，重新啟動 |
  | ERR_NGROK_3004 | HTTP 響應不完整 | 確認只有一個 Flask 進程 |

#### 5.3 查看 ngrok 日誌

打開瀏覽器訪問：`http://127.0.0.1:4040`

你會看到 LINE Verify 請求的詳細信息：
- **Request Method:** GET 或 POST
- **Status Code:** 200 (成功) 或其他代碼 (失敗)
- **Request Headers:** 包含 X-Line-Signature
- **Request Body:** 事件 JSON
- **Response:** Flask 返回的內容

---

### 🔹 第六層測試：實際 LINE 聊天測試

#### 6.1 添加 Bot 為好友

1. 找到你的 Bot 的 QR Code
   - 在 LINE Developers Console 的「Messaging API」頁面
   - 找到「Your user ID」下方的 QR Code
2. 用手機 LINE 掃描 QR Code
3. 點擊「追蹤」或「加為好友」

#### 6.2 發送命令測試

在 LINE 聊天中發送以下命令：

**基本命令：**
```
/help        # 查看所有可用命令
幫助          # /help 別名
/status      # 查看系統狀態
狀態          # /status 別名
Top5         # 查看今日 Top 5 推薦
推薦          # Top5 別名
/scan        # Top5 別名
Top5基礎     # 查看純規則推薦（不含 ML）
基礎          # Top5基礎 別名
```

**個股命令：**
```
/stock AAPL     # 查看 Apple 詳細分析
/stock MSFT     # 查看 Microsoft 分析
個股 NVDA       # 別名
查股 TSLA       # 別名
```

**市場命令：**
```
/market         # 查看宏觀環境
宏觀             # 別名
/macro          # 別名
/sector         # 查看產業動能排行
產業             # 別名
/sectors        # 別名
板塊             # 別名
```

**歷史命令：**
```
/history 0214       # 查看 2 月 14 日推薦
歷史 0215           # 查看 2 月 15 日推薦
```

**ML 命令：**
```
ML AAPL         # 查看 AAPL 的 ML 預測信心度
/ml MSFT        # 別名
```

#### 6.3 預期回應

**✅ 正常回應：**
- 文字消息立即返回（1-2 秒）
- Flex Message 卡片顯示（Top5、個股分析等）
- 表情符號和格式化非常好

**❌ 異常情況：**
- 沒有任何回應 → Flask 或 ngrok 可能有問題
- 返回錯誤信息 → 檢查數據庫連接或命令格式
- 回應延遲 (>5 秒) → 可能是數據庫查詢慢

---

## 🔍 調試技巧

### 查看 Flask 日誌

在 Flask 運行的終端中，你應該看到：

```
📨 收到 1 個事件
🔔 處理事件類型: message
✅ 簽名驗證成功
📩 收到文字消息: 'help' from U1234567890
```

### 查看 ngrok 日誌

訪問 `http://127.0.0.1:4040`

### 常見日誌錯誤

| 日誌輸出 | 原因 | 解決 |
|---------|------|------|
| ❌ 缺少 X-Line-Signature 標頭 | 請求沒有簽名 | 檢查 LINE 配置 |
| ❌ 簽名驗證失敗 | Channel Secret 錯誤 | 確認 .env 中的值 |
| ✅ 簽名驗證成功，但無回應 | 數據庫連接失敗 | 啟動 MySQL |
| 命令處理時異常 | 數據格式錯誤 | 檢查數據庫結構 |

---

## 📝 完整測試清單

```powershell
# 【第一層 - 本地端點】
☐ Flask /health 端點
☐ Flask /callback GET 端點
☐ Flask /webhook/info 端點
☐ 無簽名 POST 應該失敗

# 【第二層 - 簽名驗證】
☐ 計算正確的 HMAC-SHA256 簽名
☐ 使用正確簽名的 POST 請求成功
☐ 使用錯誤簽名的 POST 請求失敗

# 【第三層 - 模擬 LINE 事件】
☐ 模擬「文字訊息」事件
☐ 模擬「關注」事件
☐ 檢查 Flask 終端日誌

# 【第四層 - ngrok 穿透】
☐ ngrok 啟動成功
☐ 通過 ngrok URL 訪問 /callback
☐ ngrok Web Interface 查看日誌

# 【第五層 - LINE Developer Console】
☐ 更新 Webhook URL
☐ 點擊「驗証」成功
☐ 檢查 ngrok 日誌中的 Verify 請求

# 【第六層 - 實際 LINE 聊天】
☐ 在 LINE 中添加 Bot
☐ 發送 /help 命令
☐ 發送 Top5 命令
☐ 發送 /stock AAPL 命令
☐ 發送 /market 命令
☐ 檢查回應是否正常

OK/SUCCESS 標記
```

---

## 🆘 快速故障排查

### 問題：ngrok 返回 ERR_NGROK_3004

**原因：** 多個 Flask 進程運行

**解決：**
```powershell
# 清理所有進程
Get-Process python -ErrorAction SilentlyContinue | 
    Where-Object { $_.Path -like '*\.venv*' } | 
    Stop-Process -Force

# 重新啟動單個 Flask
D:/01_Project/20260101_USStock/.venv/Scripts/python.exe web/app.py
```

### 問題：LINE Verify 返回 403

**原因：** Channel Secret 不正確

**解決：**
1. 前往 LINE Developers Console
2. 複製正確的 Channel Secret
3. 更新 .env 文件
4. 重啟 Flask

### 問題：在 LINE 中沒有收到回應

**原因：** 多種可能

**排查步驟：**
```powershell
# 1. 確認 Flask 運行
netstat -ano | findstr ':6688.*LISTENING'

# 2. 確認 ngrok 運行
netstat -ano | findstr ':6688.*ESTABLISHED'

# 3. 查看 ngrok Web Interface
start http://127.0.0.1:4040

# 4. 檢查 Flask 終端日誌
# 應該看到 📨 收到事件 的日誌
```

---

## 📚 參考文檔

- [LINEBOT_NGROK_GUIDE.md](LINEBOT_NGROK_GUIDE.md) - ngrok 設置指南
- [LINEBOT_TROUBLESHOOTING.md](LINEBOT_TROUBLESHOOTING.md) - 故障排查詳解
- [NGROK_ERROR_3004_FIX.md](NGROK_ERROR_3004_FIX.md) - ERR_NGROK_3004 修復

---

**生成時間：** 2026-02-15  
**架構版本：** 1.0 (Flask 單進程 + ngrok + LINE MessageAPI)  
**當前狀態：** ✅ 所有本地端點確認正常
