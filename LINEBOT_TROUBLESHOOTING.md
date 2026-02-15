# LINE Bot 連接測試總結 & 問題排查

## ✅ 已完成事項

### 1. 數據庫數據填充
- ✅ **回測績效數據** - 4 個策略的完整回測記錄
- ✅ **產業動能數據** - 11 個主要產業，60天歷史數據
- ✅ **宏觀環境數據** - 250 筆宏觀指標數據
- ✅ **選股推薦數據** - 每日 Top 5 推薦已存在

### 2. Flask API 測試結果
```powershell
# 所有 API 端點正常運行
✅ /health              - 健康檢查
✅ /api/strategies      - 4個回測策略
✅ /api/sectors         - 11個產業動能排行
✅ /api/macro           - 宏觀環境 (RISK_ON)
✅ /api/recommendations - 每日選股推薦
```

### 3. LINE Bot Webhook 端點
```powershell
✅ GET  /callback       - 健康檢查
✅ POST /callback       - 簽名驗證已啟用
✅ GET  /webhook/info   - Webhook 配置信息
```

---

## 🔍 LINE Bot 穿透問題分析

### 您提到"之前可以做穿透"
這表示：
1. ngrok 之前是可以正常工作的
2. LINE Developer Console 配置正確
3. 可能最近有配置變更導致問題

### 常見原因分析

#### ❌ 原因 1: Flask 端口變更
**症狀：** ngrok 連接正常，但 LINE webhook 返回 503

**檢查：**
```powershell
# 確認 Flask 運行端口
Get-Process python | Where-Object { $_.MainWindowTitle -like '*Flask*' }

# 測試本地訪問
curl http://127.0.0.1:6688/health
```

**解決：**
- 確保 .env 中 `WEB_PORT=6688`
- 確保 ngrok 使用 `ngrok http 6688`

#### ❌ 原因 2: LINE_CHANNEL_SECRET 錯誤或過期
**症狀：** Webhook 顯示 403 Forbidden (簽名驗證失敗)

**檢查 .env 文件：**
```env
LINE_CHANNEL_SECRET=bbe0bb916e87ac5b42e775e9b6b4f038
LINE_CHANNEL_TOKEN=TGQXVjNIF7h4xoDRh+5JJZla0gWP6sqzHf9j...
```

**驗證步驟：**
1. 前往 [LINE Developers Console](https://developers.line.biz/console/)
2. 選擇您的 Channel
3. 進入 "Channel settings" 頁籤
4. 點擊 "Channel secret" 旁的 "Show" 按鈕
5. 完整複製並對比 .env 中的值

**❗ 重要：** 即使差一個字符都會導致簽名驗證失敗！

#### ❌ 原因 3: ngrok URL 未更新
**症狀：** LINE webhook 測試失敗或無反應

**原因：** 免費版 ngrok 每次重啟都會生成新的 URL

**解決步驟：**
1. 啟動 ngrok: `.\ngrok.exe http 6688`
2. 複製新的 HTTPS URL (例如: `https://abc123-def-456.ngrok.io`)
3. 前往 LINE Developer Console
4. 更新 "Webhook URL" 為: `https://abc123-def-456.ngrok.io/callback`
5. 點擊 **"Verify"** 按鈕測試

#### ❌ 原因 4: Windows 防火牆阻擋
**症狀：** ngrok 隧道建立，但無法接收請求

**檢查：**
```powershell
# 測試本地端口是否監聽
netstat -ano | findstr :6688

# 測試通過 localhost 訪問
Invoke-RestMethod -Uri 'http://127.0.0.1:6688/callback' -Method Get
```

**解決：**
```powershell
# 添加防火牆規則（需要管理員權限）
New-NetFirewallRule -DisplayName "Flask 6688" -Direction Inbound -LocalPort 6688 -Protocol TCP -Action Allow
```

#### ❌ 原因 5: Flask 未以 0.0.0.0 監聽
**症狀：** localhost 可訪問，但 ngrok 無法

**檢查 web/app.py：**
```python
if __name__ == '__main__':
    port = int(os.getenv('WEB_PORT', '6688'))
    # ✅ 必須是 0.0.0.0，不能是 localhost 或 127.0.0.1
    app.run(host='0.0.0.0', port=port, debug=True)
```

**當前配置：** ✅ 已經是 0.0.0.0

---

## 🎯 完整測試流程

### 步驟 1: 啟動 Flask
```powershell
# 停止舊進程
Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.Path -like '*\.venv*' } | Stop-Process -Force

# 啟動 Flask
D:/01_Project/20260101_USStock/.venv/Scripts/python.exe web/app.py
```

**預期輸出：**
```
🚀 啟動 Flask 儀表板...
   DB: localhost:3308:usstock
   訪問地址: http://0.0.0.0:6688
   Line Bot Webhook: /callback
   認證: 用戶名='admin'
 * Running on http://127.0.0.1:6688
```

### 步驟 2: 測試本地端點
```powershell
.\test_linebot.ps1
```

**預期結果：**
- ✅ /health 成功
- ✅ /webhook/info 成功 (channel_secret_configured: true)
- ✅ /callback GET 成功
- ⚠️ /callback POST 失敗 400 (缺少簽名) - **這是正常的**

### 步驟 3: 啟動 ngrok
```powershell
.\ngrok.exe http 6688
```

**檢查 ngrok 輸出：**
```
Session Status    online
Forwarding        https://abc123.ngrok.io -> http://localhost:6688
```

### 步驟 4: 打開 ngrok Web Interface
瀏覽器訪問：`http://127.0.0.1:4040`

這個界面會顯示所有進入的請求，這是調試的最佳工具！

### 步驟 5: 測試 ngrok 連通性
```powershell
# 使用您的 ngrok URL 替換下面的 URL
curl https://your-ngrok-url.ngrok.io/health
```

**預期返回：**
```json
{
  "status": "healthy",
  "database": "connected",
  "line_bot": "enabled"
}
```

### 步驟 6: 配置 LINE Developer Console

1. 前往：https://developers.line.biz/console/
2. 選擇您的 Messaging API Channel
3. 進入 "Messaging API" 設定頁面
4. 找到 "Webhook settings" 區塊
5. **Webhook URL:** `https://your-ngrok-url.ngrok.io/callback`
6. 點擊 **"Verify"** 按鈕

**✅ 成功：** 顯示 "Success" ✓
**❌ 失敗：** 查看錯誤代碼並參考上面的原因分析

### 步驟 7: 測試 LINE Bot
在 LINE 應用中：
1. 掃描 QR Code 或搜索您的 Bot
2. 發送訊息：`help`
3. 應該收到命令列表

---

## 🛠️ 調試技巧

### 1. 查看 Flask 日誌
當發送 LINE 訊息時，Flask 終端應該顯示：
```
📨 收到 1 個事件
🔔 處理事件類型: message
✅ 簽名驗證成功
📩 收到文字消息: 'help' from U1234567890
```

### 2. 查看 ngrok Web Interface
訪問 `http://127.0.0.1:4040`，可以看到：
- 每個請求的詳細信息
- 請求頭（包含 X-Line-Signature）
- 請求體
- 響應狀態碼和內容

### 3. 臨時禁用簽名驗證（僅用於測試）
如果懷疑是簽名問題，可以暫時移除 `@verify_signature` 裝飾器：

**編輯 web/bot/handler.py：**
```python
@line_bot_bp.route('/callback', methods=['POST'])
# @verify_signature  # 臨時註解掉
def callback():
    ...
```

然後重啟 Flask 並測試。如果這樣可以工作，確認是簽名配置問題。

**⚠️ 記得測試完後恢復簽名驗證！**

---

## 🔄 快速恢復清單

如果一切都不工作，按以下順序重置：

```powershell
# 1. 停止所有相關進程
Get-Process python,ngrok -ErrorAction SilentlyContinue | Stop-Process -Force

# 2. 確認端口已釋放
netstat -ano | findstr :6688

# 3. 重啟 Flask
D:/01_Project/20260101_USStock/.venv/Scripts/python.exe web/app.py

# 4. 新終端重啟 ngrok
.\ngrok.exe http 6688

# 5. 更新 LINE Webhook URL（使用新的 ngrok URL）

# 6. 測試
.\test_linebot.ps1
```

---

## 📝 當前配置摘要

```env
WEB_PORT=6688
LINE_CHANNEL_SECRET=bbe0bb916e87ac5b42e775e9b6b4f038
LINE_CHANNEL_TOKEN=TGQXVjNIF7h4xoDRh+5JJZ... (已配置)
```

```
Flask: http://0.0.0.0:6688
Endpoints:
  - GET  /health
  - GET  /callback (health check)
  - POST /callback (with signature verification)
  - GET  /webhook/info
```

數據庫：已填充完整測試數據
- ✅ 回測績效（4個策略）
- ✅ 產業動能（11個產業）
- ✅ 宏觀環境
- ✅ 選股推薦

---

## ❓ 仍然有問題？

請按以下順序提供信息：

1. **Flask 終端輸出** - 特別是啟動時的日誌
2. **ngrok 終端輸出** - Session Status 是否為 "online"
3. **LINE Verify 錯誤** - 具體的錯誤代碼（503, 403, 404 等）
4. **ngrok Web Interface 截圖** - http://127.0.0.1:4040 的請求日誌
5. **測試結果** - `.\test_linebot.ps1` 的完整輸出

這些信息能幫助快速定位問題！

---

**生成時間：** 2026-02-15  
**Flask 狀態：** ✅ 運行中 (127.0.0.1:6688)  
**數據庫：** ✅ 已填充完整數據  
**簽名驗證：** ✅ 已啟用
