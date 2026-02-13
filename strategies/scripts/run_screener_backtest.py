#!/usr/bin/env python3
"""
選股策略回測驗證

Walk-Forward 回測:
  每個月底模擬執行選股 → 買入 Top N → 持有一個月 → 計算報酬
  等權重分配, 0.1% 手續費

Usage:
    python strategies/scripts/run_screener_backtest.py
    python strategies/scripts/run_screener_backtest.py --symbols AAPL,MSFT,NVDA,GOOGL,META --months 12
"""
import argparse
import sys
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict

import pandas as pd
import numpy as np
import yfinance as yf

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / 'strategies' / 'src'))

from dotenv import load_dotenv
load_dotenv(dotenv_path=PROJECT_ROOT / '.env')

from config import BACKTEST_SYMBOLS, evaluate_stock_rules


def fetch_all_history(symbols: List[str], start: str, end: str) -> Dict[str, pd.DataFrame]:
    """批量下載歷史數據"""
    print(f"📥 下載 {len(symbols)} 支股票歷史數據 ({start} → {end}) ...")
    data = {}
    for sym in symbols:
        try:
            df = yf.Ticker(sym).history(start=start, end=end, interval='1d')
            if not df.empty and len(df) > 60:
                # 統一移除 tz 避免 tz-aware vs tz-naive 比較問題
                if df.index.tz is not None:
                    df.index = df.index.tz_localize(None)
                data[sym] = df
        except Exception as e:
            print(f"  ⚠️ {sym}: {e}")
    print(f"  ✅ 成功: {len(data)}/{len(symbols)}")
    return data


def fetch_fundamentals(symbols: List[str]) -> Dict[str, dict]:
    """批量取得基本面"""
    print(f"📥 取得 {len(symbols)} 支基本面數據 ...")
    info_map = {}
    for sym in symbols:
        try:
            info = yf.Ticker(sym).info or {}
            info_map[sym] = info
        except Exception:
            info_map[sym] = {}
    return info_map


def evaluate_at_date(
    symbol: str,
    df_full: pd.DataFrame,
    info: dict,
    eval_date: pd.Timestamp,
    lookback: int = 250,
) -> Dict:
    """
    在指定日期對股票進行策略評估（使用共用 evaluate_stock_rules）

    Args:
        df_full: 完整歷史數據
        info: 基本面
        eval_date: 評估日期
        lookback: 回看天數
    """
    # 截取到 eval_date 的歷史
    df = df_full[df_full.index <= eval_date].tail(lookback)
    if len(df) < 60:
        return None

    current_price = float(df['Close'].iloc[-1])

    result = evaluate_stock_rules(df, info)
    if result is None:
        return None

    return {
        'symbol': symbol,
        'total_score': result['rule_score'],
        'current_price': current_price,
        'passes': result['passes'],
        'breakout_pass': result['breakout']['pass'],
        'acceleration_pass': result['acceleration']['pass'],
        'peg_pass': result['peg']['pass'],
        'dupont_pass': result['dupont']['pass'],
    }


def run_backtest(symbols: List[str], months: int = 12, top_n: int = 5, fee: float = 0.001):
    """
    Walk-Forward 月度回測

    每月底:
      1. 對所有股票進行策略評估
      2. 選出 Top N
      3. 等權重買入, 持有一個月
      4. 下月底結算收益 (扣手續費)
    """
    # 計算日期範圍 (多抓 1 年歷史用於指標計算)
    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=365 * 2 + months * 30)).strftime('%Y-%m-%d')

    # 下載數據 (確保 SPY 也包含在內作為 benchmark)
    dl_symbols = list(set(symbols) | {'SPY'})
    all_data = fetch_all_history(dl_symbols, start_date, end_date)
    all_info = fetch_fundamentals(symbols)

    if not all_data:
        print("❌ 無數據可回測")
        return

    # 生成月度換倉日期
    sample_df = list(all_data.values())[0]
    all_dates = sample_df.index
    monthly_dates = all_dates.to_series().groupby(all_dates.to_period('M')).last()

    # 只取最近 N+1 個月 (需要 N+1 個點來計算 N 個期間收益)
    rebal_dates = monthly_dates.tail(months + 1).values

    if len(rebal_dates) < 2:
        print("❌ 日期不足, 需要至少 2 個月")
        return

    print(f"\n{'='*70}")
    print(f"  📈 選股策略 Walk-Forward 月度回測")
    print(f"  股票池: {len(all_data)} 支")
    print(f"  回測期間: {pd.Timestamp(rebal_dates[0]).strftime('%Y-%m-%d')} → {pd.Timestamp(rebal_dates[-1]).strftime('%Y-%m-%d')}")
    print(f"  換倉次數: {len(rebal_dates) - 1}")
    print(f"  Top-N: {top_n}")
    print(f"  手續費: {fee*100:.1f}%")
    print(f"{'='*70}\n")

    # Walk-Forward 回測
    portfolio_returns = []
    benchmark_returns = []  # SPY buy & hold

    spy_data = all_data.get('SPY')

    for i in range(len(rebal_dates) - 1):
        eval_date = pd.Timestamp(rebal_dates[i])
        next_date = pd.Timestamp(rebal_dates[i + 1])

        print(f"📅 期間 {i+1}: {eval_date.strftime('%Y-%m-%d')} → {next_date.strftime('%Y-%m-%d')}")

        # 1. 評估所有股票
        evaluations = []
        for sym, df in all_data.items():
            if sym in ('SPY', 'QQQ', 'IWM'):
                continue  # 排除指數
            result = evaluate_at_date(sym, df, all_info.get(sym, {}), eval_date)
            if result:
                evaluations.append(result)

        if not evaluations:
            print("   ⚠️ 無有效評估結果, 跳過")
            portfolio_returns.append(0.0)
            continue

        # 2. 排名 Top N
        eval_df = pd.DataFrame(evaluations).sort_values('total_score', ascending=False)
        top = eval_df.head(top_n)

        selected = top['symbol'].tolist()
        print(f"   🏆 選股: {', '.join(selected)} (score: {', '.join(f'{s:.1f}' for s in top['total_score'])})")

        # 3. 計算持倉期收益 (等權重)
        period_returns = []
        for sym in selected:
            df = all_data[sym]
            prices_in_period = df[(df.index >= eval_date) & (df.index <= next_date)]['Close']
            if len(prices_in_period) >= 2:
                ret = (prices_in_period.iloc[-1] / prices_in_period.iloc[0]) - 1
                ret_after_fee = ret - 2 * fee  # 買賣各收一次
                period_returns.append(ret_after_fee)

        if period_returns:
            avg_return = np.mean(period_returns)
        else:
            avg_return = 0.0

        portfolio_returns.append(avg_return)
        print(f"   📊 組合收益: {avg_return:+.2%}")

        # 4. Benchmark (SPY)
        if spy_data is not None:
            spy_period = spy_data[(spy_data.index >= eval_date) & (spy_data.index <= next_date)]['Close']
            if len(spy_period) >= 2:
                spy_ret = (spy_period.iloc[-1] / spy_period.iloc[0]) - 1
                benchmark_returns.append(spy_ret)
            else:
                benchmark_returns.append(0.0)
        else:
            benchmark_returns.append(0.0)

    # ================================================
    # 績效統計
    # ================================================
    cumulative = np.cumprod(1 + np.array(portfolio_returns)) - 1
    bench_cumulative = np.cumprod(1 + np.array(benchmark_returns)) - 1

    total_return = cumulative[-1] if len(cumulative) > 0 else 0
    bench_total = bench_cumulative[-1] if len(bench_cumulative) > 0 else 0

    avg_monthly = np.mean(portfolio_returns) if portfolio_returns else 0
    win_rate = sum(1 for r in portfolio_returns if r > 0) / len(portfolio_returns) if portfolio_returns else 0

    # Sharpe (月度 → 年化)
    if len(portfolio_returns) > 1 and np.std(portfolio_returns) > 0:
        sharpe = (np.mean(portfolio_returns) / np.std(portfolio_returns)) * np.sqrt(12)
    else:
        sharpe = 0

    # Max drawdown
    wealth = np.cumprod(1 + np.array(portfolio_returns))
    peak = np.maximum.accumulate(wealth)
    drawdown = (wealth - peak) / peak
    max_dd = drawdown.min() if len(drawdown) > 0 else 0

    print(f"\n{'='*70}")
    print(f"  📊 回測績效總結")
    print(f"{'='*70}")
    print(f"  策略總報酬:    {total_return:+.2%}")
    print(f"  SPY 總報酬:    {bench_total:+.2%}")
    print(f"  超額報酬:      {total_return - bench_total:+.2%}")
    print(f"  月均報酬:      {avg_monthly:+.2%}")
    print(f"  勝率:          {win_rate:.1%}")
    print(f"  年化 Sharpe:   {sharpe:.2f}")
    print(f"  最大回撤:      {max_dd:.2%}")
    print(f"  換倉次數:      {len(portfolio_returns)}")
    print(f"{'='*70}")

    # 判定
    if total_return >= 0.05:
        print(f"\n✅ 策略報酬 {total_return:.2%} >= 5% 目標, 通過！")
    else:
        print(f"\n⚠️  策略報酬 {total_return:.2%} < 5% 目標")

    # 月度明細
    print(f"\n📅 月度明細:")
    for i, (pr, br) in enumerate(zip(portfolio_returns, benchmark_returns)):
        date_str = pd.Timestamp(rebal_dates[i]).strftime('%Y-%m')
        cumul = np.cumprod(1 + np.array(portfolio_returns[:i+1]))[-1] - 1
        print(f"   {date_str}: 策略 {pr:+.2%} | SPY {br:+.2%} | 累積 {cumul:+.2%}")

    return {
        'total_return': total_return,
        'benchmark_return': bench_total,
        'sharpe': sharpe,
        'max_drawdown': max_dd,
        'win_rate': win_rate,
        'monthly_returns': portfolio_returns,
    }


def main():
    parser = argparse.ArgumentParser(description='選股策略回測')
    parser.add_argument('--symbols', type=str, default=None,
                        help='股票代碼 (逗號分隔)')
    parser.add_argument('--months', type=int, default=12,
                        help='回測月數 (預設 12)')
    parser.add_argument('--top-n', type=int, default=5,
                        help='每期選幾支 (預設 5)')
    parser.add_argument('--fee', type=float, default=0.001,
                        help='手續費比例 (預設 0.1%%)')
    args = parser.parse_args()

    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(',')]
    else:
        symbols = BACKTEST_SYMBOLS

    run_backtest(symbols, months=args.months, top_n=args.top_n, fee=args.fee)


if __name__ == '__main__':
    main()
