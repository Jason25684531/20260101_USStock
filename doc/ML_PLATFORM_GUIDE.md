# ML量化交易平台使用指南

## 概述
本平台整合了數據倉庫和機器學習功能，使用隨機森林模型進行股票預測和交易決策。

## 架構圖
```
┌─────────────────┐
│ Data Sources    │
│ • yfinance      │
│ • FRED API      │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Data Warehouse  │
│ • market_data   │
│ • macro_data    │
│ • fundamentals  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Feature Engine  │
│ • Technical     │
│ • Macro         │
│ • Fundamental   │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ ML Model        │
│ RandomForest    │
│ (100 trees)     │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Trading Signal  │
│ BUY/SELL/HOLD   │
└─────────────────┘
```

## 快速開始

### 1. 環境準備
```bash
# 進入虛擬環境
cd strategies
.\venv\Scripts\Activate.ps1

# 設置編碼（Windows）
$env:PYTHONIOENCODING="utf-8"
```

### 2. 初始化數據庫
```bash
# 執行SQL初始化腳本
Get-Content ..\database\init\06_macro_sentiment.sql -Encoding UTF8 | docker exec -i usstock_db mysql -uroot -prootpassword usstock
```

### 3. 獲取數據
```bash
# 設置要獲取的股票列表
$env:SYMBOLS="SPY,AAPL,MSFT,GOOGL,AMZN"

# 可選：設置 FRED API Key（用於宏觀數據）
# $env:FRED_API_KEY="your_fred_api_key_here"

# 執行數據獲取
python scripts/ingest_full_data.py
```

**注意**：
- 首次運行會獲取過去5年的數據
- yfinance 有 API 限制，腳本會自動添加延遲
- 如果沒有 FRED API Key，宏觀數據將被跳過（僅使用技術指標）

### 4. 訓練模型
```bash
# 使用默認設置訓練（組合多股票數據）
python train_model.py

# 或指定訓練模式和日期
$env:TRAIN_MODE="combined"  # 或 "individual"
$env:TRAIN_END_DATE="2023-12-31"
$env:TEST_START_DATE="2024-01-01"
python train_model.py
```

訓練完成後，模型將保存到 `data/model.pkl`

### 5. 使用ML策略
```python
from strategies.ml_strategy import MLStrategy

# 初始化策略
strategy = MLStrategy(
    model_path='data/model.pkl',  # 可選，默認此路徑
    buy_threshold=0.7,            # 買入閾值
    sell_threshold=0.3            # 賣出閾值
)

# 生成單個股票信號
signal, prob, details = strategy.generate_signal('AAPL')
print(f"信號: {signal}, 上漲概率: {prob:.2%}")

# 批量掃描多個股票
df_signals = strategy.scan_multiple_symbols(['AAPL', 'MSFT', 'GOOGL'])
print(df_signals)

strategy.close()
```

## 特徵說明

### 技術指標特徵（17個）
1. **RSI_14**: 相對強弱指標（14日）
2. **MACD**: MACD 值
3. **MACD_Signal**: MACD 信號線
4. **MACD_Hist**: MACD 柱狀圖
5. **SMA_Diff**: 短期/長期均線差異百分比
6. **Volatility_20**: 年化波動率（20日）
7. **Momentum_10**: 10日動量
8. **Momentum_20**: 20日動量
9. **Volume_Change**: 成交量變化百分比
10. **Volume_SMA_Ratio**: 成交量相對均值比率
11. **Price_Position**: 價格在近期區間的相對位置

### 宏觀經濟特徵（可選）
12. **UNRATE**: 失業率
13. **GDP**: GDP 數值
14. **DFF**: 聯邦基金利率
15. **CPIAUCSL**: 消費者物價指數
16. **T10Y2Y**: 十年期與兩年期國債利率差
17. **[指標]_Change**: 各指標的變化率

## 模型參數

### 隨機森林配置
```python
RandomForestClassifier(
    n_estimators=100,      # 樹的數量
    max_depth=10,          # 最大深度
    min_samples_split=20,  # 分裂所需最小樣本數
    min_samples_leaf=10,   # 葉節點最小樣本數
    class_weight='balanced',  # 處理類別不平衡
    random_state=42
)
```

### 預測標籤
- **Target = 1**: 未來5天收益率 > 2%（上漲）
- **Target = 0**: 未來5天收益率 ≤ 2%（非上漲）

### 信號生成邏輯
- **BUY**: 上漲概率 ≥ 0.7（70%）
- **SELL**: 上漲概率 ≤ 0.3（30%）
- **HOLD**: 0.3 < 上漲概率 < 0.7

## 測試和驗證

### 運行單元測試
```bash
# 測試數據獲取
python test_simple_ingest.py

# 測試完整ML流程
python test_ml_pipeline.py
```

### 預期輸出
```
✅ 特徵生成: 17 個特徵
✅ 訓練樣本: 1777 個
✅ 訓練準確率: 84.75%
✅ 測試準確率: 55.34%
✅ 模型保存成功
```

## 性能基準

根據測試數據（2020-2025模擬數據）：
- **訓練集表現**: 
  - 準確率: 84.75%
  - F1分數: 0.8122
- **測試集表現**:
  - 準確率: 55.34%
  - F1分數: 0.3895
- **訓練時間**: ~0.08秒（50棵樹）

## 最重要的特徵（Top 5）
1. **SMA_Diff** (9.00%): 短期/長期均線差異
2. **MACD** (8.72%): 趨勢強度
3. **Volatility_20** (7.60%): 市場波動性
4. **MACD_Hist** (7.24%): 動量變化
5. **Momentum_20** (6.92%): 20日動量

## 擴展和自定義

### 添加新特徵
編輯 `strategies/src/ml/features.py`：
```python
def make_features(df_price, df_macro):
    # 添加你的自定義特徵
    df['My_Feature'] = ...
    return df
```

### 調整模型參數
編輯 `strategies/train_model.py` 或直接在代碼中：
```python
model = StrategyModel(
    n_estimators=200,  # 增加樹的數量
    max_depth=15,      # 增加深度
    ...
)
```

### 修改交易閾值
```python
strategy = MLStrategy(
    buy_threshold=0.8,   # 更保守的買入（更高置信度）
    sell_threshold=0.2   # 更積極的賣出
)
```

## 故障排除

### 問題：數據庫連接失敗
```
Error: Access denied for user 'root'
```
**解決**：檢查 `.env` 文件中的 `DB_PORT` 是否設置為 `3308`

### 問題：FRED API 錯誤
```
⚠️ FRED API 不可用
```
**解決**：這是正常的。如果沒有 FRED API Key，系統會跳過宏觀數據，僅使用技術指標。

### 問題：特徵缺失警告
```
⚠️ 缺失特徵: ['UNRATE', 'GDP']
```
**解決**：這表示數據庫中沒有宏觀數據。模型會自動用 0 填充這些特徵。

## 生產部署建議

1. **定期更新數據**：每天運行 `ingest_full_data.py`
2. **定期重訓模型**：每週或每月重新訓練模型
3. **監控模型性能**：記錄預測準確率和實際收益
4. **風險管理**：
   - 不要完全依賴模型預測
   - 設置止損和止盈
   - 分散投資組合
5. **A/B測試**：比較ML策略與傳統策略的表現

## 進階功能

### 回測ML策略
```python
strategy = MLStrategy()
df_backtest = strategy.backtest_strategy(
    symbol='AAPL',
    start_date='2024-01-01',
    end_date='2025-12-31'
)
```

### 生成完整報告
```python
model = StrategyModel.load()
print(model.generate_report())
```

## 參考資源
- FinLab 機器學習教程
- Python DIY Database 文章
- sklearn RandomForestClassifier 文檔
- yfinance API 文檔
- FRED API 文檔
