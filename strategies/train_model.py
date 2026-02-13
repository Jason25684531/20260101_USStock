#!/usr/bin/env python3
"""
訓練ML模型腳本
從數據庫加載數據，訓練隨機森林模型，並保存模型
"""
import os
import sys
from pathlib import Path
from datetime import datetime
import pandas as pd
from dotenv import load_dotenv

# 加載 .env 文件
env_path = Path(__file__).parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

# 添加父目錄到路徑
sys.path.insert(0, str(Path(__file__).parent / "src"))
from adapters.database import DatabaseAdapter
from ml.features import make_features, prepare_train_test_split
from ml.model import StrategyModel


def load_data_from_db(
    symbols: list,
    db: DatabaseAdapter
) -> tuple:
    """
    從數據庫加載多個股票的數據
    
    Args:
        symbols: 股票代碼列表
        db: 數據庫適配器
        
    Returns:
        (df_price, df_macro, df_fundamental)
    """
    print(f"\n📊 從數據庫加載數據...")
    print(f"   股票列表: {', '.join(symbols)}")
    
    # 加載價格數據
    all_price_data = []
    
    for symbol in symbols:
        print(f"   加載 {symbol}...")
        df = db.get_market_data(symbol)
        
        if not df.empty:
            df['symbol'] = symbol
            all_price_data.append(df)
            print(f"      ✅ {len(df)} 條記錄")
        else:
            print(f"      ⚠️  無數據")
    
    if not all_price_data:
        raise ValueError("無法加載任何價格數據，請先運行 ingest_full_data.py")
    
    # 合併所有數據
    df_price = pd.concat(all_price_data, axis=0)
    print(f"\n   ✅ 總計加載 {len(df_price)} 條價格記錄")
    
    # 加載宏觀數據（使用 DatabaseAdapter 共用方法）
    try:
        df_macro = db.get_macro_data()
        if not df_macro.empty:
            print(f"   ✅ 加載 {len(df_macro)} 條宏觀數據記錄")
        else:
            print(f"   ⚠️  無宏觀數據，將僅使用技術指標")
    except Exception as e:
        print(f"   ⚠️  加載宏觀數據失敗: {str(e)}")
        df_macro = pd.DataFrame()
    
    # 加載基本面數據（使用 DatabaseAdapter 共用方法）
    try:
        df_fundamental = db.get_fundamental_data(symbols)
        if not df_fundamental.empty:
            print(f"   ✅ 加載 {len(df_fundamental)} 條基本面數據記錄")
        else:
            print(f"   ⚠️  無基本面數據，將僅使用技術指標")
    except Exception as e:
        print(f"   ⚠️  加載基本面數據失敗: {str(e)}")
        df_fundamental = pd.DataFrame()
    
    return df_price, df_macro, df_fundamental


def train_model_for_symbol(
    symbol: str,
    df_price: pd.DataFrame,
    df_macro: pd.DataFrame,
    df_fundamental: pd.DataFrame,
    train_end_date: str = '2023-12-31',
    test_start_date: str = '2024-01-01'
) -> StrategyModel:
    """
    為單個股票訓練模型
    
    Args:
        symbol: 股票代碼
        df_price: 價格數據
        df_macro: 宏觀數據
        df_fundamental: 基本面數據
        train_end_date: 訓練集結束日期
        test_start_date: 測試集開始日期
        
    Returns:
        訓練好的模型
    """
    print(f"\n{'='*70}")
    print(f" 🎯 訓練模型: {symbol}")
    print(f"{'='*70}")
    
    # 過濾該股票的數據
    df_symbol = df_price[df_price['symbol'] == symbol].copy()
    df_symbol = df_symbol.drop(columns=['symbol'])
    
    print(f"\n數據範圍: {df_symbol.index.min()} 到 {df_symbol.index.max()}")
    print(f"數據點數: {len(df_symbol)}")
    
    # 生成特徵（包含基本面數據）
    print(f"\n📊 生成特徵...")
    df_features = make_features(df_symbol, df_macro, df_fundamental)
    
    # 分割訓練/測試集
    X_train, y_train, X_test, y_test = prepare_train_test_split(
        df_features, 
        train_end_date=train_end_date,
        test_start_date=test_start_date
    )
    
    # 訓練模型（使用 XGBoost + 正則化）
    model = StrategyModel(
        model_type='xgboost',
        n_estimators=300,
        max_depth=5,
        learning_rate=0.01,
        random_state=42,
        reg_lambda=1.0,
        gamma=0.1
    )
    
    metrics = model.train(X_train, y_train, X_test, y_test)
    
    # 保存特徵重要性圖表
    model.save_feature_importance_plot()
    
    # 打印報告
    print(model.generate_report())
    
    return model


def train_combined_model(
    symbols: list,
    df_price: pd.DataFrame,
    df_macro: pd.DataFrame,
    df_fundamental: pd.DataFrame,
    train_end_date: str = '2023-12-31',
    test_start_date: str = '2024-01-01'
) -> StrategyModel:
    """
    使用多個股票的數據訓練一個統一模型
    
    Args:
        symbols: 股票代碼列表
        df_price: 價格數據
        df_macro: 宏觀數據
        df_fundamental: 基本面數據
        train_end_date: 訓練集結束日期
        test_start_date: 測試集開始日期
        
    Returns:
        訓練好的模型
    """
    print(f"\n{'='*70}")
    print(f" 🎯 訓練組合模型（使用所有股票數據）")
    print(f"{'='*70}")
    
    all_features = []
    
    # 為每個股票生成特徵
    for symbol in symbols:
        print(f"\n處理 {symbol}...")
        
        df_symbol = df_price[df_price['symbol'] == symbol].copy()
        df_symbol = df_symbol.drop(columns=['symbol'])
        
        if len(df_symbol) < 100:  # 跳過數據不足的股票
            print(f"   ⚠️  數據不足，跳過")
            continue
        
        try:
            df_features = make_features(df_symbol, df_macro, df_fundamental)
            all_features.append(df_features)
            print(f"   ✅ 生成 {len(df_features)} 個樣本")
        except Exception as e:
            print(f"   ❌ 生成特徵失敗: {str(e)}")
            continue
    
    if not all_features:
        raise ValueError("無法為任何股票生成特徵")
    
    # 合併所有特徵
    print(f"\n合併所有特徵...")
    df_all = pd.concat(all_features, axis=0)
    print(f"   總樣本數: {len(df_all)}")
    
    # 分割訓練/測試集
    X_train, y_train, X_test, y_test = prepare_train_test_split(
        df_all,
        train_end_date=train_end_date,
        test_start_date=test_start_date
    )
    
    # 訓練模型（使用 XGBoost + 正則化）
    model = StrategyModel(
        model_type='xgboost',
        n_estimators=500,
        max_depth=5,
        learning_rate=0.01,
        random_state=42,
        reg_lambda=1.0,
        gamma=0.1
    )
    
    metrics = model.train(X_train, y_train, X_test, y_test)
    
    # 保存特徵重要性圖表
    model.save_feature_importance_plot()
    
    # 打印報告
    print(model.generate_report())
    
    return model


def main():
    """主函數"""
    print("=" * 70)
    print(" 🤖 ML模型訓練流程")
    print("=" * 70)
    
    # 配置參數
    symbols = os.getenv('SYMBOLS', 'SPY,AAPL,MSFT,GOOGL,AMZN').split(',')
    train_mode = os.getenv('TRAIN_MODE', 'combined')  # 'combined' 或 'individual'
    train_end_date = os.getenv('TRAIN_END_DATE', '2023-12-31')
    test_start_date = os.getenv('TEST_START_DATE', '2024-01-01')
    
    print(f"\n配置:")
    print(f"   股票: {', '.join(symbols)}")
    print(f"   訓練模式: {train_mode}")
    print(f"   訓練集: 至 {train_end_date}")
    print(f"   測試集: 從 {test_start_date}")
    
    try:
        # 初始化數據庫
        db = DatabaseAdapter()
        
        # === DB 防護：檢查 macro_data 表是否存在 ===
        from sqlalchemy import text as sa_text, inspect as sa_inspect
        inspector = sa_inspect(db.engine)
        if 'macro_data' not in inspector.get_table_names():
            print("\n⚠️  macro_data 表不存在，自動建立空表...")
            try:
                with db.engine.begin() as conn:
                    conn.execute(sa_text("""
                        CREATE TABLE IF NOT EXISTS macro_data (
                            id BIGINT AUTO_INCREMENT PRIMARY KEY,
                            ticker VARCHAR(20) NOT NULL,
                            date DATE NOT NULL,
                            value DECIMAL(20, 6),
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            UNIQUE KEY uk_ticker_date (ticker, date),
                            INDEX idx_date (date)
                        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                    """))
                print("✅ macro_data 表已建立（空表，宏觀數據將作為可選特徵）")
            except Exception as e:
                print(f"   ⚠️  建立 macro_data 表失敗: {e}")
        
        # 1. 加載數據（包括基本面數據）
        df_price, df_macro, df_fundamental = load_data_from_db(symbols, db)
        
        # 2. 訓練模型
        if train_mode == 'combined':
            # 訓練一個統一模型
            model = train_combined_model(
                symbols, df_price, df_macro, df_fundamental,
                train_end_date, test_start_date
            )
            
            # 保存模型
            model.save()
            
        elif train_mode == 'individual':
            # 為每個股票訓練獨立模型
            for symbol in symbols:
                model = train_model_for_symbol(
                    symbol, df_price, df_macro, df_fundamental,
                    train_end_date, test_start_date
                )
                
                # 保存到特定文件
                model_path = Path(__file__).parent / 'data' / f'model_{symbol}.pkl'
                model.save(str(model_path))
        
        else:
            raise ValueError(f"未知的訓練模式: {train_mode}")
        
        db.close()
        
        print("\n" + "=" * 70)
        print(" ✅ 模型訓練完成！")
        print("=" * 70)
        
        # === 輸出 Test Set Accuracy + Net Profit (after fees) 摘要 ===
        if model.training_metrics.get('test'):
            tm = model.training_metrics['test']
            print(f"\n📊 測試集表現摘要:")
            print(f"   Accuracy:  {tm['accuracy']:.4f}")
            print(f"   Precision: {tm['precision']:.4f}")
            print(f"   Recall:    {tm['recall']:.4f}")
            print(f"   F1 Score:  {tm['f1']:.4f}")
            
            # 估算 Net Profit：假設每筆交易固定金額 $10,000，扣除 0.1% 手續費
            n_trades = int(tm['recall'] * model.training_metrics['n_samples'] * 0.3)  # 近似交易次數
            commission_per_trade = 10000 * 0.001  # $10
            total_fee = n_trades * commission_per_trade * 2  # 買+賣
            avg_return = 0.02 * tm['precision']  # 目標 2% × precision
            gross_profit = n_trades * 10000 * avg_return
            net_profit = gross_profit - total_fee
            print(f"\n💰 手續費影響估算 (假設每筆 $10,000):")
            print(f"   預估交易次數: {n_trades}")
            print(f"   手續費總計:   ${total_fee:,.2f}")
            print(f"   預估毛利:     ${gross_profit:,.2f}")
            print(f"   預估淨利:     ${net_profit:,.2f}")
        
        # 確認 feature_importance.png 已保存
        fi_path = Path(__file__).parent / 'data' / 'reports' / 'feature_importance.png'
        if fi_path.exists():
            print(f"\n📈 特徵重要性圖表: {fi_path}")
        
    except Exception as e:
        print(f"\n❌ 訓練過程出錯: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
