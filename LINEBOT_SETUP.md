# 🤖 LineBot 設置指南

如何從零開始配置 Line Messaging API 並使 Bot 連接到系統。

---

## 第 1 步：註冊 Line Developers 帳號

1. 前往 [Line Developers Console](https://developers.line.biz/)
2. 使用 Line 帳號登入（若無，先建立）
3. 建立新的 Provider（例如：`MyQuantBot`）

---

## 第 2 步：建立 Messaging API Channel

1. 在 Provider 下建立新的 **Messaging API Channel**
2. 填寫以下資訊：
   - **Display Name**: `USStock Bot` (或自選)
   - **Description**: Stock Screener Bot
   - **Category**: Finance
3. 同意條款並建立

### 獲取 Channel 認證資訊

建立後，在 Channel 管理頁面可找到：

- **Channel ID**: 頂部會看到
- **Channel Access Token**: 在「Channel access token」區域點擊「Issue」生成
- **Channel Secret**: 在「Basic settings」區域可見

**保存這些信息到 `.secrets/` 目錄**:

```bash
# 例如
echo "YOUR_CHANNEL_ACCESS_TOKEN" > .secrets/line_channel_token.txt
echo "YOUR_CHANNEL_SECRET" > .secrets/line_channel_secret.txt
```

---

## 第 3 步：獲取你的 User ID (收禮通知)

1. 在 Line App 中掃描你的 Bot QR Code（或按 Add Friend）
2. 向 Bot 發送任意消息（例如：「Hi」）
3. 查看 Web Dashboard 或數據庫，檢查 `line_user_id` 欄位

**或者通過日誌提取**:

```bash
# 查看 Strategy Engine 日誌
docker-compose logs strategy_engine | grep -i "user_id"

# 或查看 Web 日誌
docker-compose logs web_dashboard | grep -i "received"
```

**保存 User ID**:

```bash
echo "YOUR_USER_ID" > .secrets/line_user_id.txt
```

---

## 第 4 步：配置 Webhook URL

**開發環境 (本地調試)**:

### 使用 Ngrok 轉發

1. 安裝 [Ngrok](https://ngrok.com/) 並登入
2. 啟動隧道轉發本地端口：

```bash
ngrok http 6688
# 輸出會顯示: https://xxxxx-xxx-xxx.ngrok-free.app
```

3. 複製顯示的 HTTPS URL

### 在 Line Developers 設置 Webhook

1. 進入 Channel 管理頁面
2. 在「Messaging API」分頁找到「Webhook settings」
3. 填入：
   ```
   https://xxxxx-xxx-xxx.ngrok-free.app/callback
   ```
4. 點擊「Verify」驗證 (應返回 200 OK)
5. 開啟「Use webhook」開關

---

**生產環境**:

如果使用公網域名（例如 `example.com`），直接填入：

```
https://your-domain.com/callback
```

並確保防火牆允許 HTTPS 入站 (Port 443)。

---

## 第 5 步：配置 Rich Menu (可選)

1. 進入 Channel 管理頁面 → 「Messaging API」 → 「Rich menu」
2. 設置快捷按鈕，例如：
   - **Top5** → 今日推薦 Top 5
   - **ML Stock** → 查詢單支股票 ML 預測
   - **/help** → 顯示幫助

為了設置 Rich Menu，可使用 `setup_rich_menu.py`：

```bash
python scripts/setup_rich_menu.py
```

---

## 第 6 步：測試 Bot

### A. 向 Bot 發送命令

在 Line App 中發送以下命令到你的 Bot：

| 命令 | 別名 | 回應 |
|------|------|------|
| `Top5` | `top 5`, `推薦`, `/top5`, `/scan` | 🏆 今日推薦 Top 5 (Flex + ML 加權) |
| `Top5基礎` | `top5-basic`, `/top5basic`, `/basic`, `基礎` | 📊 今日推薦 Top 5 (純規則版，無 ML) |
| `ML AAPL` | `/ml AAPL` | 🤖 AAPL 的 ML 預測信息 |
| `/stock AAPL` | `個股 AAPL`, `查股 AAPL` | 🔍 個股分析 |
| `/market` | `市場`, `宏觀`, `/macro` | 🌍 宏觀環境 |
| `/history 0214` | `歷史 0214` | 📅 歷史推薦 |
| `/sector` | `產業`, `板塊`, `/sectors` | 🏭 產業動能排行 |
| `/status` | `狀態` | 📊 系統運行狀態 |
| `/strategies` | `策略` | 📈 列出可用策略 |
| `/help` | `幫助` | ❓ 顯示幫助選單 |

### B. 檢查日誌是否接收到消息

```bash
# 查看 Web Dashboard 日誌
docker-compose logs web_dashboard | tail -20

# 查看 Strategy Engine 日誌
docker-compose logs strategy_engine | tail -20
```

**預期日誌輸出**:
```
[Webhook] Received message from user_id: U1234567890...
[LineBot] Command: Top5, Executing screener...
[LineBot] Sending Flex Message to user...
```

### C. 測試推播通知

```bash
# 手動執行選股並發送通知
python strategies/scripts/run_daily_screener.py --save-db --notify

# 你的 Line App 應會收到 Flex Message 消息
```

---

## 常見問題 (Troubleshooting)

### Q1: Webhook 驗證失敗

**症狀**: Line Developers 顯示「Verify failed」

**解決**:
1. 確保 Web Dashboard 已啟動：`docker-compose ps` (應為 Up)
2. 檢查 `.secrets/line_channel_secret.txt` 是否正確
3. Ngrok 連接是否正常（重新啟動 Ngrok）
4. 檢查防火牆是否阻止入站流量

```bash
# 測試 Webhook 端點
curl -X POST https://xxxxx-xxx.ngrok-free.app/callback \
  -H "Content-Type: application/json" \
  -d '{"events":[]}'
# 應返回 200 OK
```

### Q2: 收不到 Bot 回應

**症狀**: 發送命令後 Bot 無反應

**解決**:
1. 確認 User ID 正確：
   ```bash
   cat .secrets/line_user_id.txt  # 不應為空
   ```
2. 查看日誌：
   ```bash
   docker-compose logs web_dashboard | grep -i "callback"
   ```
3. 確保 Webhook 切換為開啟狀態

### Q3: Flex Message 顯示混亂 (亂碼)

**症狀**: Bot 發送的消息格式錯亂

**解決**:
- 檢查 JSON 編碼是否正確（應為 UTF-8）
- 清除 Line App 快取：Settings → Chat → Clear cache
- 检查浏览器开发者工具，看 `notifier.py` 生成的 JSON 是否有效

### Q4: Ngrok 定期斷線

**症狀**: 提示「tunnel offline」

**解決**:
- 升級至 Ngrok 付費版以獲得穩定連接
- 或定期重啟 Ngrok 隧道
- 生產環境建議改用真實域名

---

## 進階設置

### 自定義命令響應

在 `web/bot/handler.py` 中修改 `handle_text_message()` 函式以添加自訂命令。

### 使用 Riсh Menu API

```bash
# 使用提供的腳本
python scripts/setup_rich_menu.py

# 或手動設置（見 Line Developers 文檔）
```

---

## 安全考量

1. **敏感信息**: 不要在代碼中硬編碼 Channel Secret 或 Token，始終使用 `.secrets/` 目錄
2. **Webhook 驗證**: 系統自動驗證 HMAC-SHA256 簽名，確保消息來自 Line 官方
3. **User ID 隱私**: User ID 應安全儲存，不應記錄到日誌中

---

## 更多資源

- [Line Developers 官方文檔](https://developers.line.biz/en/documentation/)
- [Messaging API 參考](https://developers.line.biz/en/reference/messaging-api/)
- [Flex Message 格式指南](https://developers.line.biz/en/reference/messaging-api/#flex-message)
- [Webhook 驗證說明](https://developers.line.biz/en/reference/messaging-api/#signature-validation)

---

**已完成設置?** 返回 [快速啟動指南](QUICK_START.md) 或查看 [命令速查表](COMMANDS_REFERENCE.md)
