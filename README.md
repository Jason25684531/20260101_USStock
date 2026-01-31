# USStock - 美股量化交易系統

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10-blue.svg)](https://www.python.org/)
[![Docker](https://img.shields.io/badge/docker-compose-blue.svg)](https://www.docker.com/)

## 📖 概述

這是一套自動化的美股量化交易系統，採用微服務架構，支持多策略回測、自動調度、Line Bot 通知等功能。

### 主要特點

- 🤖 **自動化調度**: APScheduler 每日美股收盤後自動執行策略分析
- 📱 **即時通知**: Line Bot 推送交易信號和每日摘要
- 📊 **多策略引擎**: Momentum, Value, Chips+Momentum, Growth PEG 等策略
- 🔐 **安全設計**: Docker Secrets 管理敏感資訊，零信任架構
- 📈 **Web Dashboard**: 視覺化回測結果和績效報告

## 🏗️ 系統架構

```
┌─────────────────────────────────────────────────────────────────┐
│                       Docker Compose 環境                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────┐    ┌───────────────┐    ┌───────────────┐    │
│  │   MySQL 8.0   │    │   Strategy    │    │      Web      │    │
│  │      db       │◄───│    Engine     │───►│   Dashboard   │    │
│  │  (Port:3308)  │    │  APScheduler  │    │  (Port:5000)  │    │
│  └──────────────┘    └───────┬───────┘    └───────┬───────┘    │
│                              │                     │            │
│                              │     Push Signal     │            │
│                              ▼                     ▼            │
│                    ┌───────────────────────────────────┐        │
│                    │       Line Messaging API          │        │
│                    │   (通知 + Webhook + Bot 命令)      │        │
│                    └───────────────────────────────────┘        │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## 📦 組件說明

| 服務 | 描述 | 技術棧 |
|------|------|--------|
| **db** | 資料庫服務 | MySQL 8.0, 持久化儲存 |
| **strategy_engine** | 策略執行引擎 | Python 3.10, VectorBT, APScheduler |
| **web_dashboard** | Web 介面 + Line Bot | Flask, Chart.js, Line Bot SDK |

## 🚀 快速開始

### 1. 環境準備

```bash
# 克隆專案
git clone <repo-url>
cd USStock

# 創建 secrets 目錄
mkdir .secrets
```

### 2. 配置 Secrets

在 `.secrets/` 目錄下創建以下文件：

```
.secrets/
├── db_root_password.txt    # MySQL root 密碼
├── db_password.txt         # 應用程式資料庫密碼
├── line_channel_token.txt  # Line Channel Access Token
├── line_channel_secret.txt # Line Channel Secret
└── line_user_id.txt        # 接收通知的 Line User ID
```

### 3. 啟動服務

**開發環境**:
```bash
docker-compose up -d
```

**生產環境**:
```bash
docker-compose -f prod.docker-compose.yml up -d
```

### 4. 驗證服務

- **Web Dashboard**: http://localhost:5000
- **健康檢查**: http://localhost:5000/health

## 📱 Line Bot 設置

### 獲取 Line Bot 憑證

1. 前往 [Line Developers Console](https://developers.line.biz/)
2. 創建 Messaging API Channel
3. 記錄以下資訊：
   - Channel Access Token → `.secrets/line_channel_token.txt`
   - Channel Secret → `.secrets/line_channel_secret.txt`
4. 在 Line App 中掃描 QR Code 加好友
5. 在 Line 對 Bot 發送任意訊息，記錄您的 User ID → `.secrets/line_user_id.txt`

### 設置 Webhook

在 Line Developers Console 設置：
- **Webhook URL**: `https://your-domain.com/bot/callback`
- **Use webhook**: 開啟
- **Auto-reply messages**: 關閉

### 支援的 Bot 命令

| 命令 | 功能 |
|------|------|
| `/help` | 顯示幫助選單 |
| `/status` | 顯示系統狀態 |
| `/summary` | 獲取最新每日摘要 |
| `/positions` | 查看當前持倉 |
| `/strategies` | 列出可用策略 |

## ⏰ 自動調度

系統使用 APScheduler 在以下時間自動執行：

- **執行時間**: 週一至週五 16:15 EST (美股收盤後)
- **執行內容**: 
  1. 下載最新市場數據
  2. 執行所有策略分析
  3. 產生交易信號
  4. 發送 Line 通知

啟用調度模式需設置環境變數：
```bash
USE_SCHEDULER=true
```

## 📊 策略列表

| 策略 | 描述 | 邏輯 |
|------|------|------|
| **Momentum** | 動量策略 | Close > 200日最高價 |
| **Value** | 價值策略 | PE < 15 且 PB < 1.5 |
| **Chips+Momentum** | 籌碼+動量 | 機構持股 > 60% + SMA 黃金交叉 |
| **Growth PEG** | 成長 PEG | PEG < 1 且 ROE > 15% |

## 🔧 開發指南

### 本地開發

```bash
# 安裝依賴
pip install -r requirements.txt

# 運行測試
cd strategies
python test_local.py

# 測試 Line 通知
python test_line_notification.py
```

### 新增策略

1. 在 `strategies/src/strategies/` 創建新策略文件
2. 繼承基礎策略接口
3. 在 `main.py` 中註冊策略
4. 更新文檔

## 📁 專案結構

```
USStock/
├── .github/workflows/     # CI/CD 配置
├── .secrets/              # 敏感資訊 (git ignored)
├── database/              # 資料庫配置
│   ├── init/              # 初始化腳本
│   └── my.cnf             # MySQL 配置
├── openspec/              # 規格文檔
│   ├── changes/           # 變更提案
│   └── specs/             # 規格定義
├── strategies/            # 策略引擎
│   ├── src/
│   │   ├── adapters/      # 數據適配器
│   │   ├── core/          # 核心回測引擎
│   │   ├── strategies/    # 策略實現
│   │   └── utils/         # 工具函數
│   └── tests/             # 測試文件
├── web/                   # Web 服務
│   ├── bot/               # Line Bot 處理器
│   ├── static/            # 靜態資源
│   └── templates/         # HTML 模板
├── docker-compose.yml     # 開發環境配置
├── prod.docker-compose.yml # 生產環境配置
└── README.md              # 本文件
```

## 📝 更新日誌

詳見 [updatelist.md](updatelist.md)

## 🔒 安全說明

- 所有敏感資訊使用 Docker Secrets 管理
- 生產環境不暴露資料庫端口
- Line Webhook 使用 HMAC-SHA256 簽名驗證
- Web Dashboard 使用 HTTP Basic Auth 保護

## 📄 授權

MIT License
