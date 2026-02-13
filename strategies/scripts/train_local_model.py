#!/usr/bin/env python3
"""
本地快速 ML 模型訓練（不需要 DB）

使用 yfinance 直接下載歷史數據，訓練 XGBoost 模型。
產出: data/model.pkl

Usage:
    python strategies/scripts/train_local_model.py
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / 'strategies' / 'src'))

import pandas as pd
import yfinance as yf
from ml.features import make_features, prepare_train_test_split
from ml.model import StrategyModel
from config import BACKTEST_SYMBOLS

# 使用 config.py 統一定義的股票池
TRAIN_SYMBOLS = BACKTEST_SYMBOLS


def main():
    print("🤖 本地 ML 模型訓練 (yfinance only, 不需要 DB)")
    print(f"   股票: {len(TRAIN_SYMBOLS)} 支")

    all_features = []
    for sym in TRAIN_SYMBOLS:
        print(f"\n📥 {sym} ...", end=" ")
        try:
            df = yf.Ticker(sym).history(period='5y', interval='1d')
            if df.empty or len(df) < 300:
                print("⚠️ 數據不足, 跳過")
                continue
            if df.index.tz is not None:
                df.index = df.index.tz_localize(None)
            df_feat = make_features(df)
            if not df_feat.empty:
                all_features.append(df_feat)
                print(f"✅ {len(df_feat)} 筆")
            else:
                print("⚠️ 特徵生成失敗")
        except Exception as e:
            print(f"❌ {e}")

    if not all_features:
        print("❌ 無法產生任何特徵")
        return

    df_all = pd.concat(all_features, axis=0)
    print(f"\n📊 合併特徵: {len(df_all)} 筆")

    X_train, y_train, X_test, y_test = prepare_train_test_split(
        df_all, train_end_date='2024-12-31', test_start_date='2025-01-01'
    )

    model = StrategyModel(
        model_type='xgboost',
        n_estimators=300,
        max_depth=5,
        learning_rate=0.01,
        random_state=42,
        reg_lambda=1.0,
        gamma=0.1,
    )
    model.train(X_train, y_train, X_test, y_test)

    # 確認 samples_dropped < 5%
    initial = sum(len(f) for f in all_features)
    dropped = initial - len(df_all)
    drop_pct = dropped / initial * 100 if initial > 0 else 0
    print(f"\n📊 NaN 丟棄率: {drop_pct:.1f}% ({'✅ < 5%' if drop_pct < 5 else '⚠️ >= 5%'})")

    model.save()  # → data/model.pkl
    print(model.generate_report())
    print("\n✅ 模型訓練完成！ data/model.pkl 已更新")


if __name__ == '__main__':
    main()
