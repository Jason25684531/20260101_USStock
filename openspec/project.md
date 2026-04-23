# USStock 量化交易系統開發計畫 (v1.1)

## 1. 系統哲學
- **目標**：機構級美股量化交易系統，結合機器學習（量化）與多智能體辯論（質化）。
- **核心原則**：
  - **數據持久化**：所有回測與 AI 辯論日誌必須存入 MySQL，拒絕「即發即棄」。
  - **雙模組決策**：混合規則過濾、XGBoost 排序與 TradingAgents (MAS) 最終審核。
  - **Open Data Platform**：使用 OpenBB 作為統一數據入口，解決 API 碎片化與數據破洞。

## 2. 技術棧 (Technology Stack)
- **基礎設施**：Docker Compose (微服務化), MySQL 8.0.
- **數據源**：
  - **OpenBB SDK**：整合 Alpaca, FMP, YFinance, FRED 等數據提供商。
- **策略與模型**：
  - **機器學習**：XGBoost (分類預測)。
  - **AI 代理**：LangGraph (TradingAgents 框架)，實作多智能體辯論。
- **交易執行**：Alpaca API (Paper Trading)。
- **通知**：LINE Messaging API (Flex Message 報告)。

## 3. 核心模組架構 (Phase 2)
### A. 數據中心 (Data Hub)
- **OpenBB Feeder**：統一抓取量價、深度財報與新聞消息面。
- **News Cache**：MySQL `news_cache` 表格，存儲歷史新聞供 Agent 回測使用。

### B. 策略引擎 (Strategy Engine)
- **篩選器**：V30-V35 規則 + XGBoost 信心加權。
- **AI Oracle**：呼叫 TradingAgents 進行「質化 Alpha」提取與風險辯論。

### C. 風控與執行 (Risk & Execution)
- **ATR Position Sizing**：基於平均真實波幅動態計算股數。
- **Market Regime Filter**：偵測 SPY 200MA 與宏觀經濟指標。
- **Intraday Monitor**：盤中即時監控支撐位與情緒崩跌。

## 4. 開發里程碑
- [x] Phase 1: 選股大腦穩定化 (V30-V35 + XGBoost)。
- [ ] Phase 2: 風控強化與 AI 決策整合 (OpenBB + TradingAgents)。
- [ ] Phase 3: 自動化執行與全自動回測管線。