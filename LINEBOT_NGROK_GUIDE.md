# LINE Bot 連接指南 - ngrok 設置

## ✅ 已完成的修復

### 1. Flask 應用配置
- ✅ 確認 Flask 運行在 **127.0.0.1:6688**
- ✅ 端口配置正確（.env 中 WEB_PORT=6688）
- ✅ Host 設置為 0.0.0.0，允許外部訪問

### 2. LINE Bot Webhook 端點修復
- ✅ 添加 GET 端點用於健康檢查：`GET /callback`
- ✅ 啟用簽名驗證：`POST /callback` 現在會驗證 X-Line-Signature
- ✅ 改進錯誤處理和日誌輸出
- ✅ 添加詳細的調試信息

### 3. 測試結果
```
✅ /health          - 健康檢查正常
✅ /webhook/info    - Webhook 配置正確
✅ /callback (GET)  - 健康檢查端點正常
⚠️ /callback (POST) - 正確拒絕無簽名的請求（預期行為）
```

---

## 🚀 ngrok 連接步驟

### 步驟 1: 確保 Flask 運行在 6688 端口
```powershell
# 檢查 Flask 是否正在運行
Get-Process python | Where-Object { $_.Path -like '*\.venv*' }

# 如果沒有運行，執行：
D:/01_Project/20260101_USStock/.venv/Scripts/python.exe web/app.py
```

你應該看到：
```
🚀 啟動 Flask 儀表板...
   DB: localhost:3308:usstock
   訪問地址: http://0.0.0.0:6688
   Line Bot Webhook: /callback
   認證: 用戶名='admin'
 * Running on http://127.0.0.1:6688
```

### 步驟 2: 啟動 ngrok
```powershell
.\ngrok.exe http 6688
```

**重要確認事項：**
- ✅ 端口號必須是 **6688**（不是 5000, 5051 或其他）
- ✅ ngrok 狀態要顯示 "online"
- ✅ 記下 ngrok 提供的 HTTPS URL（例如：`https://abc123.ngrok.io`）

### 步驟 3: 檢查 ngrok Web Interface
打開瀏覽器訪問：**http://127.0.0.1:4040**

這是 ngrok 的監控界面，可以看到：
- 所有進入的請求
- 請求和響應的詳細信息
- 錯誤消息（如果有）

### 步驟 4: 配置 LINE Developer Console

1. 前往 [LINE Developers Console](https://developers.line.biz/console/)
2. 選擇你的 Channel
3. 進入 "Messaging API" 設定頁面
4. 設置 Webhook URL：
   ```
   https://your-ngrok-url.ngrok.io/callback
   ```
   **注意：** 替換 `your-ngrok-url` 為你的 ngrok URL

5. 點擊 **"Verify"** 按鈕

### 步驟 5: 驗證結果

#### ✅ 成功的情況：
- LINE 顯示：Success ✓
- ngrok 監控界面顯示 GET 請求，返回 200
- 你可以在 LINE 聊天中發送 "help" 測試

#### ❌ 常見錯誤及解決方案：

| 錯誤代碼 | 原因 | 解決方案 |
|---------|------|---------|
| **503** | Flask 沒運行或端口不對 | 確認 Flask 在 6688 運行 |
| **404** | URL 路徑錯誤 | 確認 URL 以 `/callback` 結尾 |
| **400** | 缺少簽名標頭 | LINE 應該自動加上，檢查是否為測試請求 |
| **403** | 簽名驗證失敗 | 檢查 .env 中的 LINE_CHANNEL_SECRET |

---

## 🔍 故障排除

### 問題 1: ngrok 顯示 503
**原因：** Flask 沒有運行或端口不匹配

**檢查：**
```powershell
# 測試 Flask 是否可訪問
Invoke-RestMethod -Uri 'http://127.0.0.1:6688/health' -Method Get
```

如果失敗，重啟 Flask：
```powershell
D:/01_Project/20260101_USStock/.venv/Scripts/python.exe web/app.py
```

### 問題 2: 簽名驗證失敗 (403)
**原因：** LINE_CHANNEL_SECRET 不正確

**檢查 .env 文件：**
```env
LINE_CHANNEL_SECRET=你的真實 Channel Secret
LINE_CHANNEL_TOKEN=你的真實 Channel Access Token
```

**確認方式：**
1. 前往 LINE Developers Console
2. Channel Settings > Channel Secret（點擊顯示）
3. 複製完整的 Secret 並更新 .env
4. 重啟 Flask

### 問題 3: ngrok URL 過期
**原因：** 免費版 ngrok URL 每次重啟都會改變

**解決：**
- 每次重啟 ngrok 後，都需要更新 LINE Developer Console 的 Webhook URL
- 考慮升級到 ngrok 付費版以獲得固定 URL

### 問題 4: 防火牆阻擋
**檢查：**
```powershell
# 測試本地訪問
curl http://127.0.0.1:6688/health

# 測試通過 ngrok 訪問
curl https://your-ngrok-url.ngrok.io/health
```

---

## 🧪 手動測試命令

### 測試所有端點：
```powershell
.\test_linebot.ps1
```

### 單獨測試：
```powershell
# Health Check
Invoke-RestMethod -Uri 'http://127.0.0.1:6688/health' -Method Get | ConvertTo-Json

# Webhook Info
Invoke-RestMethod -Uri 'http://127.0.0.1:6688/webhook/info' -Method Get | ConvertTo-Json

# Callback Health (GET)
Invoke-RestMethod -Uri 'http://127.0.0.1:6688/callback' -Method Get | ConvertTo-Json
```

---

## 📝 快速檢查清單

使用此清單確保所有設置正確：

- [ ] Flask 運行在 127.0.0.1:6688
- [ ] 可以訪問 http://127.0.0.1:6688/health
- [ ] ngrok 運行在端口 6688
- [ ] ngrok 狀態顯示 "online"
- [ ] ngrok Web Interface (http://127.0.0.1:4040) 可訪問
- [ ] LINE Developer Console Webhook URL 已更新
- [ ] LINE Developer Console Webhook URL 以 /callback 結尾
- [ ] LINE_CHANNEL_SECRET 在 .env 中正確配置
- [ ] LINE_CHANNEL_TOKEN 在 .env 中正確配置
- [ ] 點擊 LINE "Verify" 按鈕顯示成功

---

## 🎯 測試 LINE Bot 功能

設置完成後，在 LINE 聊天中發送：

```
help
```

你應該看到完整的命令列表。

再試試：
```
Top5
```

應該返回今日推薦的股票。

---

## 📞 需要幫助？

如果仍然遇到問題：

1. 檢查 Flask 終端的錯誤消息
2. 檢查 ngrok Web Interface (http://127.0.0.1:4040) 的請求日誌
3. 確認 .env 文件中的憑證正確無誤
4. 運行 `.\test_linebot.ps1` 查看詳細測試結果

---

**生成時間：** 2026-02-15  
**Flask 端口：** 127.0.0.1:6688  
**Webhook 端點：** /callback
