# LINE Bot 連接測試腳本
Write-Host "🧪 測試 LINE Bot 連接..." -ForegroundColor Cyan
Write-Host ""

# 1. 測試健康檢查端點
Write-Host "1️⃣ 測試 /health 端點..." -ForegroundColor Yellow
try {
    $health = Invoke-RestMethod -Uri 'http://127.0.0.1:6688/health' -Method Get
    Write-Host "✅ Health Check 成功:" -ForegroundColor Green
    $health | ConvertTo-Json | Write-Host
} catch {
    Write-Host "❌ Health Check 失敗: $_" -ForegroundColor Red
}
Write-Host ""

# 2. 測試 LINE Webhook Info 端點
Write-Host "2️⃣ 測試 /webhook/info 端點..." -ForegroundColor Yellow
try {
    $info = Invoke-RestMethod -Uri 'http://127.0.0.1:6688/webhook/info' -Method Get
    Write-Host "✅ Webhook Info 成功:" -ForegroundColor Green
    $info | ConvertTo-Json | Write-Host
} catch {
    Write-Host "❌ Webhook Info 失敗: $_" -ForegroundColor Red
}
Write-Host ""

# 3. 測試 LINE Callback GET (健康檢查)
Write-Host "3️⃣ 測試 /callback GET 端點..." -ForegroundColor Yellow
try {
    $callback = Invoke-RestMethod -Uri 'http://127.0.0.1:6688/callback' -Method Get
    Write-Host "✅ Callback GET 成功:" -ForegroundColor Green
    $callback | ConvertTo-Json | Write-Host
} catch {
    Write-Host "❌ Callback GET 失敗: $_" -ForegroundColor Red
}
Write-Host ""

# 4. 測試 LINE Callback POST (模擬空事件 - 應該成功但無簽名驗證時會被拒絕)
Write-Host "4️⃣ 測試 /callback POST 端點 (無簽名)..." -ForegroundColor Yellow
try {
    $body = @{
        events = @()
    } | ConvertTo-Json
    
    $callback = Invoke-RestMethod -Uri 'http://127.0.0.1:6688/callback' -Method Post -ContentType 'application/json' -Body $body
    Write-Host "✅ Callback POST 成功 (簽名驗證可能已禁用):" -ForegroundColor Green
    $callback | ConvertTo-Json | Write-Host
} catch {
    Write-Host "⚠️  Callback POST 失敗 (預期行為，因缺少簽名): $_" -ForegroundColor Yellow
}
Write-Host ""

Write-Host "=" -repeat 60 -ForegroundColor Cyan
Write-Host "📋 測試結果摘要:" -ForegroundColor Cyan
Write-Host "   ✅ 如果 1-3 都成功，表示 Flask 正常運行" -ForegroundColor White
Write-Host "   🔧 如果 4 失敗（403/400），是正常的（缺少簽名）" -ForegroundColor White
Write-Host "   🌐 使用 ngrok 時，請將 URL 設為: https://your-ngrok-url/callback" -ForegroundColor White
Write-Host "=" -repeat 60 -ForegroundColor Cyan
