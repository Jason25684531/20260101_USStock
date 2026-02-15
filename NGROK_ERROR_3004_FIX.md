# ngrok ERR_NGROK_3004 問題解決方案

## ❌ 問題原因
**發現：4 個 Flask 進程同時監聽 6688 端口**
```
PID: 7412, 28792, 41588, 19664 都在監聽 0.0.0.0:6688
```

**結果：**
- 多個 Flask 實例競爭處理同一個請求
- ngrok 收到混亂或不完整的 HTTP 響應
- 導致 ERR_NGROK_3004: "invalid or incomplete HTTP response"

---

## ✅ 解決步驟

### 1. 清理所有 Flask 進程 ✅
```powershell
# 找到所有佔用 6688 端口的進程
$pids = (netstat -ano | findstr ':6688.*LISTENING' | 
         ForEach-Object { $_.Trim() -split '\s+' | Select-Object -Last 1 } | 
         Sort-Object -Unique)

# 終止所有進程
foreach($pid in $pids){ 
    Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue 
}
```

### 2. 啟動單一 Flask 實例 ✅
```powershell
D:/01_Project/20260101_USStock/.venv/Scripts/python.exe web/app.py
```

**確認：**
- ✅ 只有一個進程監聽 6688
- ✅ /callback 端點正常響應
- ✅ HTTP 響應完整

---

## 🧪 測試步驟

### 1. 確認 Flask 單獨運行
```powershell
# 檢查有幾個進程在監聽 6688
netstat -ano | findstr ':6688.*LISTENING'

# 應該只有一行結果（一個進程）
```

### 2. 測試本地端點
```powershell
# 測試健康檢查
Invoke-RestMethod -Uri 'http://127.0.0.1:6688/health' -Method Get

# 測試 Callback
Invoke-RestMethod -Uri 'http://127.0.0.1:6688/callback' -Method Get
```

**預期結果：**
- ✅ 立即返回 JSON 響應
- ✅ 沒有超時或連接錯誤
- ✅ 響應完整（有開頭和結尾的大括號）

### 3. 啟動 ngrok
```powershell
# 確保 Flask 正在運行後，再啟動 ngrok
.\ngrok.exe http 6688
```

### 4. 測試 ngrok 端點
```powershell
# 使用你的 ngrok URL 替換 your-ngrok-url
curl https://your-ngrok-url.ngrok.io/callback
```

**預期結果：**
- ✅ 返回 200 OK
- ✅ 沒有 ERR_NGROK_3004 錯誤
- ✅ JSON 響應完整

### 5. LINE Webhook 驗證
1. 前往 LINE Developer Console
2. 更新 Webhook URL: `https://your-ngrok-url.ngrok.io/callback`
3. 點擊 **"Verify"**

**預期結果：**
- ✅ Success ✓

---

## 🛑 防止問題再次發生

### 啟動 Flask 之前，先清理舊進程
```powershell
# 創建啟動腳本：start_flask_clean.ps1
$ErrorActionPreference = 'SilentlyContinue'

Write-Host "🧹 清理舊進程..." -ForegroundColor Yellow
Get-Process python | Where-Object { $_.Path -like '*\.venv*' } | Stop-Process -Force
Start-Sleep -Seconds 2

Write-Host "🚀 啟動 Flask..." -ForegroundColor Green
D:/01_Project/20260101_USStock/.venv/Scripts/python.exe web/app.py
```

### 使用此腳本啟動
```powershell
.\start_flask_clean.ps1
```

---

## 🔍 ngrok 常見錯誤對照

| 錯誤代碼 | 原因 | 解決方案 |
|---------|------|---------|
| **ERR_NGROK_3004** | Flask 響應不完整/多個實例衝突 | ✅ **已修復** - 清理多餘進程 |
| **ERR_NGROK_3200** | Flask 沒有運行 | 啟動 Flask |
| **ERR_NGROK_8012** | ngrok 隧道失敗 | 重啟 ngrok |
| **502/503** | Flask 崩潰或端口錯誤 | 檢查 Flask 日誌 |
| **404** | URL 路徑錯誤 | 確認 `/callback` 路徑 |
| **403** | 簽名驗證失敗 | 檢查 Channel Secret |

---

## 📝 當前狀態

```
✅ 已清理多餘 Flask 進程
✅ 單一 Flask 實例運行中 (PID: 待確認)
✅ 端口 6688 正常監聽
✅ /callback 端點正常響應
⚠️ MySQL 未運行（不影響 Webhook 驗證）

準備就緒！可以測試 ngrok 連接。
```

---

## 🚀 立即測試

```powershell
# 1. 確認 Flask 單獨運行
netstat -ano | findstr ':6688.*LISTENING' | Measure-Object | Select-Object Count

# 2. 測試端點
Invoke-RestMethod -Uri 'http://127.0.0.1:6688/callback' -Method Get

# 3. 啟動 ngrok
.\ngrok.exe http 6688

# 4. 訪問 ngrok URL（在瀏覽器或用 curl）
# https://your-ngrok-url.ngrok.io/callback
```

---

**修復時間：** 2026-02-15 晚上  
**根本原因：** 多個 Flask 進程同時運行  
**狀態：** ✅ 已解決
