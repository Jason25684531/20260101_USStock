@echo off
:: 設定 CMD 編碼為 UTF-8，避免中文亂碼
chcp 65001 >nul

echo ===================================================
echo 🚀 啟動美股量化系統每日排程 (V35 完備版)
echo 📅 執行時間: %date% %time%
echo ===================================================

:: 切換到專案根目錄 (確保排程器在哪裡啟動都不會迷路)
cd /d D:\01_Project\20260101_USStock

:: 啟動虛擬環境 (非常重要，確保吃到正確的套件)
call .venv\Scripts\activate

echo.
echo [1/2] 啟動 OpenBB Feeder，寫入最新 K 線至 MySQL...
python strategies/scripts/openbb_feeder.py
if %ERRORLEVEL% neq 0 (
    echo ❌ OpenBB Feeder 執行失敗，中斷後續排程！
    pause
    exit /b %ERRORLEVEL%
)

echo.
echo [2/2] 啟動選股引擎，進行 ML 運算與 Line 推播...
python strategies/scripts/run_daily_screener.py --save-db --notify
if %ERRORLEVEL% neq 0 (
    echo ❌ 選股引擎執行失敗！
    pause
    exit /b %ERRORLEVEL%
)

echo.
echo ✅ 任務全數完成！Line 決策卡片已發送。
:: 排程器執行時不需要 pause，如果您手動點擊想看結果，可以把下面這行取消註解
:: pause