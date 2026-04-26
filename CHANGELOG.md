# Changelog

This file tracks release-ready changes for the US Stock system. Legacy historical notes remain in [doc/updatelist.md](doc/updatelist.md).

## 2026-04-26 - V35 完備版

### ✨ 新功能 (Features)
- 引入「聰明錢」籌碼追蹤，將法人持股與內部人交易情緒納入每日推薦資料契約。
- 整合華爾街目標價 `targetMeanPrice` 與估值區間計算，輸出 `target_price`、`fair_price`、`buy_price`、`sell_price`、`valuation_status`。
- 恢復 `support_1` / `resistance_1` 決策維度，讓三層式 Flex Card 回到「現價 / 目標 / 支撐 / 壓力」的完整錨定資訊。
- 實作動態推薦理由生成 `reason_summary`，將量化策略訊號轉譯為自然語言摘要。
- 升級 LineBot Flex Message 為三層高密度決策卡片，包含估值狀態、價格區間、籌碼與 AI 勝率、推薦理由。

### 🔧 系統優化與重構 (Improvements & Tech Debt)
- 統一被動查詢 [web/bot/handler.py](web/bot/handler.py) 與主動推播 [strategies/src/adapters/notifier.py](strategies/src/adapters/notifier.py) 的 Flex UI 邏輯，抽離共用格式化 helper 至 [strategies/src/utils/line_flex.py](strategies/src/utils/line_flex.py)。
- 實作全域 Null-safe / NaN handling，修復 `daily_recommendations` 寫入時的 schema 演進與浮點髒資料中斷問題，並避免 Flex Card 因缺值崩潰。
- Web 戰情室支援 Dark Theme，並修復圖表與交易列表的畫面塌陷問題。
- 完成封存前架構清理：移除重複 Flex helper、更新過期 manual check 腳本、清除暫存 `__pycache__` 目錄，降低後續維護成本並保留擴充性。