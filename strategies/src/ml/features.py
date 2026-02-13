"""
特徵工程模塊
結合價格、技術指標和宏觀經濟數據生成ML特徵
"""
import numpy as np
import pandas as pd
from typing import Optional


def calculate_rsi(prices: pd.Series, period: int = 14) -> pd.Series:
    """
    計算相對強弱指標 (RSI)

    委派至 config.calc_rsi 統一實作。

    Args:
        prices: 收盤價序列
        period: 計算週期，默認14天

    Returns:
        RSI 值序列 (0-100)
    """
    from config import calc_rsi
    return calc_rsi(prices, period)


def calculate_macd(
    prices: pd.Series, 
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9
) -> pd.DataFrame:
    """
    計算 MACD 指標
    
    Args:
        prices: 收盤價序列
        fast_period: 快線週期，默認12
        slow_period: 慢線週期，默認26
        signal_period: 信號線週期，默認9
        
    Returns:
        包含 MACD, Signal, Histogram 的 DataFrame
    """
    ema_fast = prices.ewm(span=fast_period, adjust=False).mean()
    ema_slow = prices.ewm(span=slow_period, adjust=False).mean()
    
    macd = ema_fast - ema_slow
    signal = macd.ewm(span=signal_period, adjust=False).mean()
    histogram = macd - signal
    
    return pd.DataFrame({
        'MACD': macd,
        'MACD_Signal': signal,
        'MACD_Hist': histogram
    })


def calculate_sma_diff(prices: pd.Series, short_period: int = 20, long_period: int = 50) -> pd.Series:
    """
    計算短期與長期移動平均線的差異百分比
    
    Args:
        prices: 收盤價序列
        short_period: 短期週期，默認20天
        long_period: 長期週期，默認50天
        
    Returns:
        SMA 差異百分比序列
    """
    sma_short = prices.rolling(window=short_period).mean()
    sma_long = prices.rolling(window=long_period).mean()
    
    sma_diff = ((sma_short - sma_long) / sma_long) * 100
    
    return sma_diff


def calculate_volatility(prices: pd.Series, period: int = 20) -> pd.Series:
    """
    計算歷史波動率
    
    Args:
        prices: 收盤價序列
        period: 計算週期，默認20天
        
    Returns:
        年化波動率序列
    """
    returns = prices.pct_change()
    volatility = returns.rolling(window=period).std() * np.sqrt(252)
    
    return volatility


def calculate_momentum(prices: pd.Series, period: int = 10) -> pd.Series:
    """
    計算動量指標（當前價格相對N天前的變化百分比）
    
    Args:
        prices: 收盤價序列
        period: 回看週期，默認10天
        
    Returns:
        動量百分比序列
    """
    momentum = ((prices - prices.shift(period)) / prices.shift(period)) * 100
    
    return momentum


def calculate_distance_from_ma(prices: pd.Series, period: int = 200) -> pd.Series:
    """
    計算價格與移動平均線的距離百分比
    
    Args:
        prices: 收盤價序列
        period: MA週期，默認200天
        
    Returns:
        距離百分比序列
    """
    ma = prices.rolling(window=period).mean()
    distance = ((prices - ma) / ma) * 100
    
    return distance


def calculate_52week_high_distance(prices: pd.Series) -> pd.Series:
    """
    計算當前價格與52週高點的距離
    
    Args:
        prices: 收盤價序列
        
    Returns:
        距離百分比序列（負值表示低於高點）
    """
    high_52w = prices.rolling(window=252).max()  # 252個交易日 ≈ 52週
    distance = ((prices - high_52w) / high_52w) * 100
    
    return distance


def calculate_volume_volatility(volume: pd.Series, period: int = 20) -> pd.Series:
    """
    計算成交量波動率
    
    Args:
        volume: 成交量序列
        period: 計算週期，默認20天
        
    Returns:
        成交量波動率序列
    """
    volume_change = volume.pct_change()
    vol_volatility = volume_change.rolling(window=period).std() * np.sqrt(252)
    
    return vol_volatility


def _fetch_spy_close(index: pd.DatetimeIndex) -> Optional[pd.Series]:
    """
    取得 SPY 收盤價序列（用於計算相對強度）。
    嘗試 yfinance 下載；失敗時返回 None。
    確保日期完全對齊（去除時區 + reindex + ffill）。
    """
    try:
        import yfinance as yf
        start = (index.min() - pd.Timedelta(days=10)).strftime('%Y-%m-%d')
        end = (index.max() + pd.Timedelta(days=1)).strftime('%Y-%m-%d')
        df_spy = yf.download('SPY', start=start, end=end, progress=False, auto_adjust=True)
        if isinstance(df_spy.columns, pd.MultiIndex):
            df_spy.columns = df_spy.columns.droplevel(1)
        if df_spy.empty:
            return None
        # 移除時區資訊以確保與 stock index 相容
        if df_spy.index.tz is not None:
            df_spy.index = df_spy.index.tz_localize(None)
        spy_close = df_spy['Close']
        # 將 stock index 也統一為 tz-naive
        clean_index = index.tz_localize(None) if index.tz is not None else index
        # 精確到日期對齊：先 normalize 再 reindex + ffill
        spy_close.index = spy_close.index.normalize()
        clean_index_norm = clean_index.normalize()
        return spy_close.reindex(clean_index_norm, method='ffill')
    except Exception:
        return None


def calculate_relative_strength_spy(
    prices: pd.Series,
    spy_close: Optional[pd.Series],
    period: int = 63
) -> pd.Series:
    """
    計算相對強度 (Relative Strength vs SPY)
    
    公式: Stock_Return_Nd / SPY_Return_Nd
    識別在市場修正中仍跑贏大盤的個股。
    確保 SPY 日期與個股完全對齊後再做除法。
    
    Args:
        prices: 個股收盤價序列
        spy_close: SPY 收盤價序列（已對齊索引），None 時回傳 0
        period: 回看天數，默認 63 天（≈3個月）
    
    Returns:
        相對強度比值序列
    """
    stock_ret = prices.pct_change(periods=period)
    if spy_close is None:
        return pd.Series(0.0, index=prices.index)
    spy_ret = spy_close.pct_change(periods=period)
    # 避免除零
    rs = stock_ret / spy_ret.replace(0, np.nan)
    return rs.fillna(0)


def calculate_volume_price_trend(prices: pd.Series, volume: pd.Series, period: int = 10) -> pd.Series:
    """
    計算量價共振指標 (Volume-Price Trend)
    
    以滾動相關性衡量「價格上漲是否伴隨成交量放大」。
    高正值 → 量價齊升（強勢）；高負值 → 量價背離（弱勢）。
    
    Args:
        prices: 收盤價序列
        volume: 成交量序列
        period: 滾動窗口，默認 10 天
    
    Returns:
        量價相關性序列 (-1 ~ 1)
    """
    price_change = prices.pct_change()
    vol_change = volume.pct_change()
    vpt = price_change.rolling(window=period).corr(vol_change)
    return vpt.fillna(0)


def make_features(
    df_price: pd.DataFrame,
    df_macro: Optional[pd.DataFrame] = None,
    df_fundamental: Optional[pd.DataFrame] = None,
    target_days: int = 5,
    target_threshold: float = 0.02
) -> pd.DataFrame:
    """
    生成機器學習特徵（NaN-Resistant 版本）
    
    整合價格數據、技術指標、宏觀經濟數據和基本面數據，生成完整的特徵集
    採用智能填充策略，避免因宏觀/基本面數據稀疏而丟失價格數據
    
    Args:
        df_price: 價格數據 DataFrame，必須包含 'Close' 列，索引為日期
        df_macro: 宏觀經濟數據 DataFrame，索引為日期，列為各指標（可選）
        df_fundamental: 基本面數據 DataFrame，包含 PEG, ROE 等（可選）
        target_days: 預測未來N天的收益，默認5天
        target_threshold: 判定為"上漲"的閾值，默認2%
        
    Returns:
        包含特徵和標籤的 DataFrame
    """
    df = df_price.copy()

    # 統一去除時區資訊（yfinance 可能返回 tz-aware DatetimeIndex）
    if hasattr(df.index, 'tz') and df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    
    # 確保 Close 列存在
    if 'Close' not in df.columns and 'close' in df.columns:
        df['Close'] = df['close']
    
    if 'Close' not in df.columns:
        raise ValueError("價格數據必須包含 'Close' 或 'close' 列")
    
    print(f"   📊 開始特徵生成（初始數據: {len(df)} 行）...")
    
    # ===== 1. 核心技術指標特徵（必備） =====
    
    # RSI
    df['RSI_14'] = calculate_rsi(df['Close'], period=14)
    
    # MACD
    macd_df = calculate_macd(df['Close'])
    df['MACD'] = macd_df['MACD']
    df['MACD_Signal'] = macd_df['MACD_Signal']
    df['MACD_Hist'] = macd_df['MACD_Hist']
    
    # SMA 差異
    df['SMA_Diff'] = calculate_sma_diff(df['Close'], short_period=20, long_period=50)
    
    # 波動率
    df['Volatility_20'] = calculate_volatility(df['Close'], period=20)
    
    # 動量
    df['Momentum_10'] = calculate_momentum(df['Close'], period=10)
    df['Momentum_20'] = calculate_momentum(df['Close'], period=20)
    
    # ===== 2. 進階技術動量特徵 =====
    
    # 價格與 200 日均線距離
    df['Distance_MA200'] = calculate_distance_from_ma(df['Close'], period=200)
    
    # 52週高點距離
    df['Distance_52W_High'] = calculate_52week_high_distance(df['Close'])
    
    # 成交量特徵
    if 'Volume' in df.columns or 'volume' in df.columns:
        volume_col = 'Volume' if 'Volume' in df.columns else 'volume'
        df['Volume_Change'] = df[volume_col].pct_change() * 100
        df['Volume_SMA_Ratio'] = df[volume_col] / df[volume_col].rolling(window=20).mean()
        df['Volume_Volatility'] = calculate_volume_volatility(df[volume_col], period=20)
    
    # 價格相對位置（當前價格在近期最高最低之間的位置）
    df['Price_Position'] = (df['Close'] - df['Close'].rolling(window=20).min()) / \
                           (df['Close'].rolling(window=20).max() - df['Close'].rolling(window=20).min())
    
    # ===== 2.5 進階動量 Alpha 特徵 =====
    
    # 相對強度 vs SPY（自動下載 SPY 數據，失敗時以 0 填充）
    spy_close = _fetch_spy_close(df.index)
    df['Rel_Strength_SPY'] = calculate_relative_strength_spy(df['Close'], spy_close, period=63)
    df['Rel_Strength_SPY'] = df['Rel_Strength_SPY'].ffill().fillna(0)
    
    # 量價共振 (Volume-Price Trend)
    if 'Volume' in df.columns or 'volume' in df.columns:
        vol_col = 'Volume' if 'Volume' in df.columns else 'volume'
        df['Volume_Price_Trend'] = calculate_volume_price_trend(df['Close'], df[vol_col], period=10)
        df['Volume_Price_Trend'] = df['Volume_Price_Trend'].ffill().fillna(0)
    
    # ===== 3. 基本面特徵（高Alpha因子） =====
    
    if df_fundamental is not None and not df_fundamental.empty:
        print(f"   💎 合併基本面數據...")
        df_fundamental = df_fundamental.copy()
        
        # 刪除 df 中與 df_fundamental 重疊的列，避免 join 時發生衝突
        overlap_cols = df.columns.intersection(df_fundamental.columns)
        if len(overlap_cols) > 0:
            print(f"      移除重複列: {', '.join(overlap_cols)}")
            df = df.drop(columns=overlap_cols)
        
        # 確保基本面數據的所有列都是數值類型
        for col in df_fundamental.columns:
            df_fundamental[col] = pd.to_numeric(df_fundamental[col], errors='coerce')
        
        # 合併基本面數據（使用前向填充，因為基本面數據更新頻率低）
        df = df.join(df_fundamental, how='left')
        
        # 關鍵基本面指標
        fundamental_cols = ['peg_ratio', 'pe_ratio', 'pb_ratio', 'roe', 
                          'revenue_growth_yoy', 'earnings_growth_yoy',
                          'inst_ownership_pct', 'market_cap']
        
        # 智能填充：前向填充 -> 後向填充 -> 填0（對於真正缺失的數據）
        for col in fundamental_cols:
            if col in df.columns:
                df[col] = df[col].ffill().bfill().fillna(0)
        
        # 計算 ROE 動量（如果有足夠的 ROE 數據）
        if 'roe' in df.columns:
            df['ROE_Momentum'] = df['roe'].diff(periods=63)  # 約3個月（63個交易日）的變化
            df['ROE_Momentum'] = df['ROE_Momentum'].fillna(0)
    
    # ===== 4. 宏觀經濟特徵（可選，不應影響樣本數） =====
    
    if df_macro is not None and not df_macro.empty:
        print(f"   🌐 合併宏觀數據...")
        df_macro = df_macro.copy()
        
        # 刪除 df 中與 df_macro 重疊的列，避免 join 時發生衝突
        overlap_cols = df.columns.intersection(df_macro.columns)
        if len(overlap_cols) > 0:
            print(f"      移除重複列: {', '.join(overlap_cols)}")
            df = df.drop(columns=overlap_cols)
        
        # 確保宏觀數據的所有列都是數值類型
        for col in df_macro.columns:
            df_macro[col] = pd.to_numeric(df_macro[col], errors='coerce')
        
        # 使用前向填充合併宏觀數據（因為宏觀數據通常是低頻的）
        df = df.join(df_macro, how='left')
        
        # 智能填充宏觀數據：前向填充 -> 後向填充 -> 填中位數
        macro_cols = df_macro.columns.tolist()
        for col in macro_cols:
            if col in df.columns:
                # 先前向填充（最常見的情況）
                df[col] = df[col].ffill()
                # 如果開頭還有 NaN，使用後向填充
                df[col] = df[col].bfill()
                # 如果還有 NaN（極端情況），用中位數填充
                if df[col].isna().any():
                    median_val = df[col].median()
                    df[col] = df[col].fillna(median_val if pd.notna(median_val) else 0)
        
        # 計算宏觀指標的變化率（使用較短的週期避免產生太多 NaN）
        for col in macro_cols:
            if col in df.columns:
                df[f'{col}_Change'] = df[col].pct_change(periods=10) * 100
                df[f'{col}_Change'] = df[f'{col}_Change'].fillna(0)
    
    # ===== 5. 創建目標標籤 =====
    
    # 計算未來收益率
    df['Future_Return'] = (df['Close'].shift(-target_days) / df['Close'] - 1)
    
    # 二元分類標籤：未來是否上漲超過閾值
    df['Target'] = (df['Future_Return'] > target_threshold).astype(int)
    
    # ===== 6. 智能數據清理（NaN-Resistant） =====
    
    initial_len = len(df)
    
    # 定義核心必備特徵（只有這些缺失時才刪除行）
    critical_features = [
        'Close', 'RSI_14', 'MACD', 'SMA_Diff', 
        'Volatility_20', 'Momentum_10'
    ]
    
    # 確保核心特徵存在
    critical_features = [col for col in critical_features if col in df.columns]
    
    # 只刪除核心特徵缺失的行（非常保守的策略）
    df = df.dropna(subset=critical_features)
    
    # 對於其餘的 NaN，用 0 填充（表示"無數據"而非"缺失錯誤"）
    feature_cols = [col for col in df.columns 
                   if col not in ['Target', 'Future_Return', 'Open', 'High', 'Low', 'Close', 'Volume',
                                  'open', 'high', 'low', 'close', 'volume', 'symbol']]
    
    for col in feature_cols:
        if df[col].isna().any():
            df[col] = df[col].fillna(0)
    
    # 統計信息
    rows_dropped = initial_len - len(df)
    rows_with_target = df['Target'].notna().sum()
    
    print(f"   ✅ 特徵生成完成: {len(feature_cols)} 個特徵")
    print(f"   📈 數據行數: {initial_len} -> {len(df)} (移除 {rows_dropped} 行)")
    print(f"   🎯 有效訓練樣本: {rows_with_target} 個")
    
    if rows_with_target == 0:
        print(f"   ⚠️  警告：沒有有效的訓練樣本！檢查數據範圍或 target_days 參數")
    
    return df


def get_feature_columns(df: pd.DataFrame) -> list:
    """
    獲取所有特徵列（排除目標列和原始價格列）
    
    Args:
        df: 包含特徵的 DataFrame
        
    Returns:
        特徵列名列表
    """
    # 排除的列
    exclude_cols = [
        'Open', 'High', 'Low', 'Close', 'Volume', 'Adj Close',
        'open', 'high', 'low', 'close', 'volume', 'adj_close',
        'Target', 'Future_Return', 'symbol', 'created_at', 'updated_at',
        'id',  # 資料庫主鍵，不應作為特徵
    ]
    
    feature_cols = [col for col in df.columns if col not in exclude_cols]
    
    return feature_cols


def prepare_train_test_split(
    df: pd.DataFrame,
    train_end_date: str = '2023-12-31',
    test_start_date: str = '2024-01-01'
) -> tuple:
    """
    分割訓練集和測試集（基於時間）
    
    Args:
        df: 包含特徵和標籤的 DataFrame
        train_end_date: 訓練集結束日期
        test_start_date: 測試集開始日期
        
    Returns:
        (X_train, y_train, X_test, y_test)
    """
    # 獲取特徵列
    feature_cols = get_feature_columns(df)
    
    # 移除沒有標籤的行（最後幾行）
    df_with_target = df.dropna(subset=['Target'])
    
    # 時間分割
    train_mask = df_with_target.index <= train_end_date
    test_mask = df_with_target.index >= test_start_date
    
    X_train = df_with_target.loc[train_mask, feature_cols]
    y_train = df_with_target.loc[train_mask, 'Target']
    X_test = df_with_target.loc[test_mask, feature_cols]
    y_test = df_with_target.loc[test_mask, 'Target']
    
    print(f"\n📊 訓練/測試集分割:")
    print(f"   訓練集: {len(X_train)} 樣本 (至 {train_end_date})")
    print(f"   測試集: {len(X_test)} 樣本 (從 {test_start_date})")
    print(f"   特徵數量: {len(feature_cols)}")
    
    return X_train, y_train, X_test, y_test
