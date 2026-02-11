#!/usr/bin/env python3
"""
每日選股推薦 CLI

Usage:
    python strategies/scripts/run_daily_screener.py
    python strategies/scripts/run_daily_screener.py --top-n 10
    python strategies/scripts/run_daily_screener.py --symbols AAPL,MSFT,NVDA --use-ml
    python strategies/scripts/run_daily_screener.py --save-db --notify
"""
import argparse
import sys
import os
from pathlib import Path
from datetime import date

# 路徑設定
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / 'strategies' / 'src'))

from dotenv import load_dotenv
load_dotenv(dotenv_path=PROJECT_ROOT / '.env')

from screener.engine import DailyScreener, DEFAULT_SYMBOLS


def print_report(recommendations, df_all):
    """印出選股報告"""
    print(f"\n{'='*80}")
    print(f"  📊 每日選股推薦報告 — {date.today()}")
    print(f"{'='*80}")

    if not recommendations:
        print("  ❌ 無推薦結果")
        return

    # Top N 推薦表
    print(f"\n🏆 Top {len(recommendations)} 推薦:")
    print(f"{'─'*80}")
    print(f"{'排名':>4} {'代碼':<8} {'價格':>10} {'評分':>6} "
          f"{'突破':>4} {'加速':>4} {'PEG':>4} {'杜邦':>4} "
          f"{'支撐':>10} {'壓力':>10}")
    print(f"{'─'*80}")

    for rec in recommendations:
        s1 = rec.get('support_1')
        r1 = rec.get('resistance_1')
        print(
            f"  #{rec['rank']:<3} {rec['symbol']:<8} "
            f"${rec['current_price']:>8.2f} "
            f"{rec['total_score']:>5.2f} "
            f"{'✓' if rec['breakout_pass'] else '✗':>4} "
            f"{'✓' if rec['acceleration_pass'] else '✗':>4} "
            f"{'✓' if rec['peg_pass'] else '✗':>4} "
            f"{'✓' if rec['dupont_pass'] else '✗':>4} "
            f"${s1:>8.2f} " if s1 else f"{'N/A':>10} "
            f"${r1:>8.2f}" if r1 else f"{'N/A':>10}"
        )

    # 掃描統計
    if df_all is not None and not df_all.empty:
        buy_count = len(df_all[df_all['signal'] == 'BUY'])
        sell_count = len(df_all[df_all['signal'] == 'SELL'])
        avg_score = df_all['total_score'].mean()
        print(f"\n📈 掃描統計:")
        print(f"   BUY 標的: {buy_count}")
        print(f"   SELL 標的: {sell_count}")
        print(f"   平均評分: {avg_score:.2f}")
        print(f"   最高評分: {df_all['total_score'].max():.2f}")

    # 各策略詳情
    print(f"\n📋 策略明細:")
    for rec in recommendations:
        print(f"\n  {'─'*40}")
        print(f"  {rec['symbol']} (${rec['current_price']:.2f})")
        sd = rec['strategy_details']
        for name, label in [('breakout', '創新高'), ('acceleration', '加速度'),
                            ('peg', 'PEG'), ('dupont', '杜邦')]:
            strat = sd.get(name, {})
            icon = '✅' if strat.get('pass') else '❌'
            details = strat.get('details', '')
            print(f"    {icon} {label}: {details}")
        if rec.get('pe_ratio'):
            print(f"    📊 PE={rec['pe_ratio']:.1f}", end="")
            if rec.get('peg_ratio'):
                print(f"  PEG={rec['peg_ratio']:.2f}", end="")
            if rec.get('pb_ratio'):
                print(f"  PB={rec['pb_ratio']:.2f}", end="")
            if rec.get('roe'):
                roe_pct = rec['roe'] * 100
                print(f"  ROE={roe_pct:.1f}%", end="")
            print()

    print(f"\n{'='*80}")


def main():
    parser = argparse.ArgumentParser(description='每日選股推薦系統')
    parser.add_argument('--symbols', type=str, default=None,
                        help='股票代碼 (逗號分隔), 預設 51 支美股')
    parser.add_argument('--top-n', type=int, default=5,
                        help='推薦數量 (預設 5)')
    parser.add_argument('--use-ml', action='store_true',
                        help='啟用 ML 信心度加權')
    parser.add_argument('--save-db', action='store_true',
                        help='結果存入 DB')
    parser.add_argument('--notify', action='store_true',
                        help='推送 Line 通知')
    parser.add_argument('--delay', type=float, default=0.3,
                        help='yfinance 請求間隔秒數 (預設 0.3)')
    args = parser.parse_args()

    # 解析股票池
    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(',')]
    else:
        symbols = DEFAULT_SYMBOLS

    print(f"🚀 啟動每日選股系統")
    print(f"   股票池: {len(symbols)} 支")
    print(f"   Top-N: {args.top_n}")
    print(f"   ML 加權: {'是' if args.use_ml else '否'}")
    print(f"   存入 DB: {'是' if args.save_db else '否'}")
    print(f"   Line 通知: {'是' if args.notify else '否'}")

    # 初始化選股引擎
    screener = DailyScreener(
        symbols=symbols,
        use_ml=args.use_ml,
        top_n=args.top_n,
        delay=args.delay,
    )

    try:
        # 掃描
        df_all = screener.scan_all()

        if df_all.empty:
            print("❌ 無掃描結果")
            return

        # 取得推薦
        recommendations = screener.get_top_recommendations(df_all, n=args.top_n)

        # 印出報告
        print_report(recommendations, df_all)

        # 存入 DB
        if args.save_db:
            screener.save_to_db(recommendations)

        # Line 通知
        if args.notify:
            try:
                from adapters.notifier import get_notifier
                notifier = get_notifier()
                msg = screener.format_line_message(recommendations)
                if notifier.is_enabled:
                    notifier.send_text(msg)
                    print("✅ Line 通知已發送")
                else:
                    print("⚠️  Line 未配置, 訊息如下:")
                    print(msg)
            except Exception as e:
                print(f"⚠️  Line 通知失敗: {e}")

        print(f"\n✅ 選股完成！")

    finally:
        screener.close()


if __name__ == '__main__':
    main()
