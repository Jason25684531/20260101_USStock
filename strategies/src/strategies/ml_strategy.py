import pandas as pd
import xgboost as xgb
from sqlalchemy import create_engine
import warnings

# 引入集中管理的配置檔 (Phase 2 微服務架構)
from strategies.src.config import DB_URI, UNIVERSE_TICKERS

# 忽略 Pandas 的一些 FutureWarning
warnings.filterwarnings('ignore')

# 建立 MySQL 連線引擎
engine = create_engine(DB_URI)

# ==========================================
# 1. 資料讀取層 (Data Access Layer) - 斷開外部網路！
# ==========================================
def load_data_from_db(symbol: str) -> pd.DataFrame:
    """
    從本地 MySQL (price_data_v2) 讀取歷史量價資料，完全斷開 yfinance 等外部依賴。
    """
    query = f"SELECT * FROM price_data_v2 WHERE symbol = '{symbol}' ORDER BY date ASC"
    
    try:
        df = pd.read_sql(query, con=engine)
        
        if df.empty:
            print(f"⚠️ [資料庫] 找不到 {symbol} 的數據，請確認 Feeder 是否有抓取。")
            return df
            
        # 轉換日期格式並設為 Index (滿足機器學習特徵對齊的需求)
        df['date'] = pd.to_datetime(df['date'])
        df.set_index('date', inplace=True)
        
        # 確保數值型態正確
        for col in ['open', 'high', 'low', 'close', 'volume']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
                
        return df
        
    except Exception as e:
        print(f"❌ [資料庫] 讀取 {symbol} 失敗: {e}")
        return pd.DataFrame()

# ==========================================
# 2. 特徵工程層 (Feature Engineering) - V30~V35 規則
# ==========================================
def calculate_v30_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    在這裡貼上你原本的 V30-V35 數學公式與技術指標計算。
    """
    if df.empty:
        return df
        
    df = df.copy()
    
    # --- ⬇️ 請將你原本的公式貼在這裡 ⬇️ ---
    # 範例：計算簡單的移動平均與動能
    df['SMA_5'] = df['close'].rolling(window=5).mean()
    df['SMA_20'] = df['close'].rolling(window=20).mean()
    df['Momentum_10'] = df['close'] / df['close'].shift(10) - 1
    # --- ⬆️ 貼上你原本的公式 ⬆️ ---
    
    # 移除因為計算均線而產生的 NaN
    df.dropna(inplace=True)
    return df

# ==========================================
# 3. 模型預測層 (Model Inference)
# ==========================================
def run_xgboost_inference(features_df: pd.DataFrame, symbol: str) -> float:
    """
    執行 XGBoost 模型推論，回傳最新一天的信心度分數。
    """
    if len(features_df) < 1:
        return 0.0
        
    # 取出最新一天 (最後一筆) 的特徵作為今日預測基準
    latest_data = features_df.iloc[-1:]
    
    # 定義你的特徵欄位名稱 (必須跟你訓練模型時一模一樣)
    # --- ⬇️ 請替換為你實際使用的特徵名稱 ⬇️ ---
    feature_cols = ['SMA_5', 'SMA_20', 'Momentum_10'] 
    X_pred = latest_data[feature_cols]
    
    # 【選項 A】載入你預先訓練好的本地模型檔案
    # model = xgb.XGBClassifier()
    # model.load_model('models/xgboost_v35.json')
    # prob = model.predict_proba(X_pred)[0][1] # 取買入的機率
    
    # 【選項 B】假設目前是回測開發階段，給個隨機假分數做管線測試
    import random
    prob = random.uniform(0.3, 0.95)
    
    return round(prob, 4)

# ==========================================
# 4. 主程式 (Strategy Engine 執行入口)
# ==========================================
def run_daily_screener():
    print("🤖 啟動 XGBoost 策略初篩引擎 (V35-Local)...")
    
    results = []
    
    for symbol in UNIVERSE_TICKERS:
        # 1. 讀取數據 (從 DB)
        df = load_data_from_db(symbol)
        
        if not df.empty:
            # 2. 算特徵
            features_df = calculate_v30_features(df)
            
            # 3. 跑模型
            score = run_xgboost_inference(features_df, symbol)
            
            # 記錄結果
            results.append({
                "symbol": symbol,
                "latest_close": features_df['close'].iloc[-1],
                "xgboost_score": score
            })
            
    # 4. 產出 Top 清單 (依據分數降序排列)
    if results:
        results_df = pd.DataFrame(results)
        results_df = results_df.sort_values(by="xgboost_score", ascending=False).reset_index(drop=True)
        
        print("\n🏆 今日量化初篩 Top 名單：")
        print(results_df.head(10).to_string())
        return results_df.head(10)
    else:
        print("⚠️ 今日無符合條件的標的。")
        return pd.DataFrame()

if __name__ == "__main__":
    # 單元測試入口
    top_candidates = run_daily_screener()