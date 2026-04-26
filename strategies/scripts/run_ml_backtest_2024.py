#!/usr/bin/env python3
"""
run_ml_backtest_2024.py — Walk-Forward OOS 回測（2024-01 → 今天）

邏輯:
    1. 載入預訓練模型 (data/model.pkl — 訓練集截止 2023-12-31)
    2. 逐日遍歷 2024-01-01 至今，用模型做 BUY/HOLD 決策
    3. 計算策略累計報酬 vs SPY Buy-and-Hold 累計報酬
    4. 輸出 equity curve 圖 → data/reports/ml_performance_2024.png

執行方式:
    cd strategies
    python scripts/run_ml_backtest_2024.py [--symbol AAPL] [--start 2024-01-01]
"""
import argparse
import os
import sys
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd

# === 路徑設定 ===
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent  # 20260101_USStock
STRATEGIES_ROOT = PROJECT_ROOT / "strategies"

sys.path.insert(0, str(STRATEGIES_ROOT / "src"))

from ml.model import StrategyModel
from ml.features import make_features

# matplotlib（可選）
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False


# =============================================
# Yahoo Finance 小工具（離線回測不依賴 DB）
# =============================================
def fetch_yfinance(symbol: str, start: str, end: str) -> pd.DataFrame:
    """從 yfinance 下載歷史價格"""
    try:
        import yfinance as yf
        df = yf.download(symbol, start=start, end=end, progress=False, auto_adjust=True)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
        if df.empty:
            print(f"⚠️  yfinance 無 {symbol} 數據 ({start} ~ {end})")
        return df
    except Exception as e:
        print(f"❌ yfinance 下載失敗: {e}")
        return pd.DataFrame()


def fetch_yfinance_fundamentals(symbol: str) -> pd.DataFrame:
    """
    從 yfinance 獲取基本面數據，構造與訓練時一致的 DataFrame。
    用於離線回測時補齊基本面特徵，避免特徵數量不匹配。
    """
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        info = ticker.info

        fundamentals = {
            'peg_ratio': info.get('pegRatio'),
            'pe_ratio': info.get('trailingPE'),
            'pb_ratio': info.get('priceToBook'),
            'roe': info.get('revenueGrowth'),  # 與 train_model 一致
            'revenue_growth_yoy': info.get('revenueGrowth'),
            'earnings_growth_yoy': info.get('earningsGrowth'),
            'inst_ownership_pct': info.get('heldPercentInstitutions'),
            'market_cap': info.get('marketCap'),
        }

        # 轉為數值，None → NaN
        for k, v in fundamentals.items():
            fundamentals[k] = pd.to_numeric(v, errors='coerce') if v is not None else np.nan

        # 構造單行 DataFrame，索引為今天（會被 ffill 展開）
        df = pd.DataFrame([fundamentals], index=pd.DatetimeIndex([pd.Timestamp.now().normalize()]))
        df.index.name = 'data_date'
        return df
    except Exception as e:
        print(f"   ⚠️  yfinance 基本面獲取失敗: {e}")
        return pd.DataFrame()


# =============================================
# Walk-Forward 回測核心
# =============================================
def run_walk_forward(
    model: StrategyModel,
    symbol: str,
    start_date: str = "2024-01-01",
    end_date: str = None,
    buy_threshold: float = 0.65,
    sell_threshold: float = 0.40,
    commission_rate: float = 0.001,
) -> pd.DataFrame:
    """
    Walk-Forward OOS 回測

    Args:
        model: 預訓練 StrategyModel
        symbol: 目標股票代碼
        start_date: 回測起始日
        end_date: 回測結束日（None = 今天）
        buy_threshold: BUY 概率閾值
        sell_threshold: SELL 概率閾值
        commission_rate: 單邊手續費率 (默認 0.1%)

    Returns:
        df_result: DataFrame (date, close, signal, up_prob, strategy_return, bh_return)
    """
    if end_date is None:
        end_date = datetime.now().strftime("%Y-%m-%d")

    # 需要充足的回看期來計算技術指標（200日MA + 52w high = ~252 天）
    lookback_start = pd.Timestamp(start_date) - pd.DateOffset(days=400)
    lookback_str = lookback_start.strftime("%Y-%m-%d")

    print(f"📥 下載 {symbol} 數據: {lookback_str} → {end_date}")
    df_price = fetch_yfinance(symbol, lookback_str, end_date)
    if df_price.empty:
        return pd.DataFrame()

    # 獲取基本面數據（使同回測特徵數量與訓練時一致）
    print(f"📥 獲取 {symbol} 基本面數據...")
    df_fundamental = fetch_yfinance_fundamentals(symbol)

    # 生成特徵（包含基本面數據以匹配訓練時的 26 個特徵）
    print("🔧 生成特徵...")
    df_features = make_features(df_price, df_macro=None, df_fundamental=df_fundamental)

    # 過濾到回測期
    df_bt = df_features.loc[start_date:end_date].copy()
    if df_bt.empty:
        print("⚠️  回測期無有效數據")
        return pd.DataFrame()

    # 確保特徵列與模型一致
    for feat in model.feature_names:
        if feat not in df_bt.columns:
            df_bt[feat] = 0

    X = df_bt[model.feature_names]

    # 預測
    print("🤖 模型推論中...")
    probas = model.predict_proba(X)
    df_bt["up_prob"] = probas[:, 1]

    # 生成信號
    df_bt["signal"] = "HOLD"
    df_bt.loc[df_bt["up_prob"] >= buy_threshold, "signal"] = "BUY"
    df_bt.loc[df_bt["up_prob"] <= sell_threshold, "signal"] = "SELL"

    # ===== 策略報酬（Long-Only Cash Management） =====
    df_bt["daily_return"] = df_bt["Close"].pct_change()
    # Long-Only hysteresis：BUY 進場、SELL 出場、HOLD 沿用前一日狀態。
    current_position = 0
    position_states = []
    for signal in df_bt["signal"]:
        if signal == "BUY":
            current_position = 1
        elif signal == "SELL":
            current_position = 0
        position_states.append(current_position)

    df_bt["position"] = pd.Series(position_states, index=df_bt.index)
    # 隔日才能反映信號（信號在收盤生成，隔日開盤執行）
    df_bt["position"] = df_bt["position"].shift(1).fillna(0)
    df_bt["strategy_daily"] = df_bt["position"] * df_bt["daily_return"]
    df_bt["strategy_cum"] = (1 + df_bt["strategy_daily"]).cumprod() - 1

    # ===== Net Equity (after fees) =====
    # 每次換倉扣除手續費（單邊）
    df_bt["position_change"] = df_bt["position"].diff().abs()
    df_bt["fee"] = df_bt["position_change"].fillna(0) * commission_rate
    df_bt["strategy_net_daily"] = df_bt["strategy_daily"] - df_bt["fee"]
    df_bt["strategy_net_cum"] = (1 + df_bt["strategy_net_daily"]).cumprod() - 1

    # ===== Buy-and-Hold =====
    df_bt["bh_cum"] = (1 + df_bt["daily_return"]).cumprod() - 1

    # 結果摘要
    total_days = len(df_bt)
    buy_days = (df_bt["signal"] == "BUY").sum()
    sell_days = (df_bt["signal"] == "SELL").sum()
    strategy_return = df_bt["strategy_cum"].iloc[-1] if len(df_bt) > 0 else 0
    net_return = df_bt["strategy_net_cum"].iloc[-1] if len(df_bt) > 0 else 0
    bh_return = df_bt["bh_cum"].iloc[-1] if len(df_bt) > 0 else 0

    print(f"\n{'='*60}")
    print(f" 📊 Walk-Forward 回測結果 — {symbol}")
    print(f"{'='*60}")
    print(f"   回測期間: {start_date} → {end_date}")
    print(f"   閾值設定: BUY >= {buy_threshold:.2f} | SELL <= {sell_threshold:.2f}")
    print(f"   交易日數: {total_days}")
    print(f"   BUY 天數: {buy_days}   SELL 天數: {sell_days}   HOLD 天數: {total_days - buy_days - sell_days}")
    print(f"   策略累計報酬 (Gross): {strategy_return:+.2%}")
    print(f"   策略累計報酬 (Net):   {net_return:+.2%}  [手續費 {commission_rate*100:.1f}%]")
    print(f"   Buy & Hold:            {bh_return:+.2%}")
    print(f"   超額報酬 (Net):        {net_return - bh_return:+.2%}")

    return df_bt


# =============================================
# SPY 對比
# =============================================
def fetch_spy_benchmark(start_date: str, end_date: str) -> pd.Series:
    """下載 SPY 累計報酬作為 Benchmark"""
    df_spy = fetch_yfinance("SPY", start_date, end_date)
    if df_spy.empty:
        return pd.Series(dtype=float)
    spy_ret = df_spy["Close"].pct_change()
    spy_cum = (1 + spy_ret).cumprod() - 1
    return spy_cum


# =============================================
# 繪圖
# =============================================
def plot_equity(
    df_bt: pd.DataFrame,
    symbol: str,
    spy_cum: pd.Series,
    save_path: str,
    buy_threshold: float,
    sell_threshold: float,
):
    """繪製 Equity Curve 對比圖"""
    if not MATPLOTLIB_AVAILABLE:
        print("⚠️  matplotlib 未安裝，跳過繪圖")
        return

    fig, axes = plt.subplots(2, 1, figsize=(14, 9), gridspec_kw={"height_ratios": [3, 1]})

    # --- 上圖: Equity Curve ---
    ax1 = axes[0]
    ax1.plot(df_bt.index, df_bt["strategy_cum"] * 100, label=f"ML Gross ({symbol})", linewidth=2, color="#2196F3")
    ax1.plot(df_bt.index, df_bt["strategy_net_cum"] * 100, label=f"ML Net ({symbol})", linewidth=2, color="#1565C0", linestyle="-.")
    ax1.plot(df_bt.index, df_bt["bh_cum"] * 100, label=f"Buy & Hold ({symbol})", linewidth=1.5, color="#FF9800", linestyle="--")
    if not spy_cum.empty:
        # 對齊索引
        spy_aligned = spy_cum.reindex(df_bt.index, method="ffill")
        ax1.plot(spy_aligned.index, spy_aligned * 100, label="SPY Buy & Hold", linewidth=1.5, color="#4CAF50", linestyle=":")
    ax1.set_ylabel("Cumulative Return (%)")
    ax1.set_title(f"ML Walk-Forward Backtest — {symbol} (OOS)", fontsize=14, fontweight="bold")
    ax1.legend(loc="upper left")
    ax1.grid(True, alpha=0.3)
    ax1.axhline(0, color="black", linewidth=0.5)

    # --- 下圖: 每日預測概率 ---
    ax2 = axes[1]
    up_prob_pct = df_bt["up_prob"] * 100
    buy_threshold_pct = buy_threshold * 100
    sell_threshold_pct = sell_threshold * 100
    ax2.plot(df_bt.index, up_prob_pct, color="#263238", linewidth=1.2, label="Up Probability")
    ax2.fill_between(
        df_bt.index,
        up_prob_pct,
        buy_threshold_pct,
        where=df_bt["up_prob"] >= buy_threshold,
        alpha=0.35,
        color="#4CAF50",
        label="Buy Zone",
    )
    ax2.fill_between(
        df_bt.index,
        up_prob_pct,
        sell_threshold_pct,
        where=df_bt["up_prob"] <= sell_threshold,
        alpha=0.35,
        color="#F44336",
        label="Sell Zone",
    )
    ax2.axhline(buy_threshold_pct, color="green", linestyle="--", linewidth=0.8, label=f"Buy Threshold ({buy_threshold_pct:.0f}%)")
    ax2.axhline(sell_threshold_pct, color="red", linestyle="--", linewidth=0.8, label=f"Sell Threshold ({sell_threshold_pct:.0f}%)")
    ax2.set_ylabel("Up Probability (%)")
    ax2.set_xlabel("Date")
    ax2.legend(loc="upper right", fontsize=8)
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    Path(save_path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"\n📈 圖表已保存: {save_path}")


# =============================================
# Main
# =============================================
def main():
    parser = argparse.ArgumentParser(description="ML Walk-Forward OOS Backtest")
    parser.add_argument("--symbol", default="AAPL", help="目標股票代碼 (default: AAPL)")
    parser.add_argument("--start", default="2024-01-01", help="回測起始日 (default: 2024-01-01)")
    parser.add_argument("--end", default=None, help="回測結束日 (default: 今天)")
    parser.add_argument("--model", default=None, help="模型路徑 (default: data/model.pkl)")
    parser.add_argument("--buy-threshold", type=float, default=0.65)
    parser.add_argument("--sell-threshold", type=float, default=0.40)
    args = parser.parse_args()

    print("=" * 60)
    print(" 🤖 ML Walk-Forward OOS Backtest")
    print("=" * 60)

    # 載入模型
    model_path = args.model
    if model_path is None:
        model_path = str(PROJECT_ROOT / "data" / "model.pkl")
    print(f"📂 載入模型: {model_path}")
    model = StrategyModel.load(model_path)

    # 執行回測
    df_bt = run_walk_forward(
        model=model,
        symbol=args.symbol,
        start_date=args.start,
        end_date=args.end,
        buy_threshold=args.buy_threshold,
        sell_threshold=args.sell_threshold,
    )

    if df_bt.empty:
        print("❌ 回測失敗")
        return

    # SPY 基準
    end = args.end or datetime.now().strftime("%Y-%m-%d")
    spy_cum = fetch_spy_benchmark(args.start, end)

    # 繪圖
    report_dir = PROJECT_ROOT / "data" / "reports"
    plot_path = str(report_dir / "ml_performance_2024.png")
    plot_equity(
        df_bt,
        args.symbol,
        spy_cum,
        plot_path,
        buy_threshold=args.buy_threshold,
        sell_threshold=args.sell_threshold,
    )

    # 保存 CSV
    csv_path = str(report_dir / "ml_backtest_2024.csv")
    report_dir.mkdir(parents=True, exist_ok=True)
    df_bt[["Close", "signal", "up_prob", "strategy_cum", "strategy_net_cum", "bh_cum"]].to_csv(csv_path)
    print(f"📄 CSV 已保存: {csv_path}")

    print("\n✅ Walk-Forward 回測完成")


if __name__ == "__main__":
    main()
