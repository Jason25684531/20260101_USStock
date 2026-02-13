"""
基於機器學習的交易策略
使用訓練好的模型進行預測和交易決策
"""
import os
import sys
from pathlib import Path
from typing import Tuple
import pandas as pd
import numpy as np
from dotenv import load_dotenv

# 加載 .env 文件
env_path = Path(__file__).parent.parent.parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

# 添加路徑
sys.path.insert(0, str(Path(__file__).parent.parent))
from adapters.database import DatabaseAdapter
from adapters.market_data import fetch_data
from ml.features import make_features, get_feature_columns
from ml.model import StrategyModel


class MLStrategy:
    """
    基於機器學習的交易策略
    
    策略邏輯:
    1. 從數據庫加載歷史數據
    2. 生成技術指標和宏觀特徵
    3. 使用訓練好的模型預測未來走勢
    4. 根據預測概率做出交易決策
    """
    
    def __init__(
        self,
        model_path: str = None,
        buy_threshold: float = 0.55,
        sell_threshold: float = 0.3
    ):
        """
        初始化ML策略
        
        Args:
            model_path: 模型文件路徑，默認為 data/model.pkl
            buy_threshold: 買入閾值（預測概率 > 該值時買入）
            sell_threshold: 賣出閾值（預測概率 < 該值時賣出）
        """
        self.model = StrategyModel.load(model_path)
        self.buy_threshold = buy_threshold
        self.sell_threshold = sell_threshold
        
        self.db = DatabaseAdapter()
        
        print(f"✅ ML策略初始化完成")
        print(f"   買入閾值: {buy_threshold}")
        print(f"   賣出閾值: {sell_threshold}")
    
    def generate_signal(
        self,
        symbol: str,
        lookback_days: int = 365
    ) -> Tuple[str, float, dict]:
        """
        為指定股票生成交易信號
        
        Args:
            symbol: 股票代碼
            lookback_days: 回看天數（用於計算技術指標）
            
        Returns:
            (信號, 置信度, 詳細信息)
            信號: 'BUY', 'SELL', 'HOLD'
            置信度: 0-1之間的概率值
            詳細信息: 包含特徵值和預測細節的字典
        """
        try:
            # 1. 獲取價格數據
            print(f"\n🔍 分析 {symbol}...")
            df_price = self._get_price_data(symbol, lookback_days)
            
            if df_price.empty:
                print(f"   ⚠️  無法獲取 {symbol} 的數據")
                return 'HOLD', 0.0, {'error': '無數據'}
            
            # 2. 獲取宏觀數據
            df_macro = self._get_macro_data()
            
            # 2.5 獲取基本面數據
            df_fundamental = self._get_fundamental_data(symbol)
            
            # 3. 生成特徵（包含基本面數據）
            df_features = make_features(df_price, df_macro, df_fundamental)
            
            if df_features.empty:
                print(f"   ⚠️  無法生成特徵")
                return 'HOLD', 0.0, {'error': '特徵生成失敗'}
            
            # 4. 取最新一行數據進行預測
            latest_features = df_features.iloc[[-1]]  # 保持 DataFrame 格式
            
            # 確保特徵列與模型訓練時一致
            feature_cols = get_feature_columns(latest_features)
            
            # 檢查是否有缺失的特徵
            missing_features = set(self.model.feature_names) - set(feature_cols)
            if missing_features:
                print(f"   ⚠️  缺失特徵: {missing_features}")
                # 用0填充缺失的特徵
                for feat in missing_features:
                    latest_features[feat] = 0
            
            # 選擇與訓練時相同的特徵（保持順序）
            X = latest_features[self.model.feature_names]
            
            # 5. 進行預測
            proba = self.model.predict_proba(X)[0]
            up_prob = proba[1]  # 上漲概率
            
            # 6. 生成交易信號
            if up_prob >= self.buy_threshold:
                signal = 'BUY'
            elif up_prob <= self.sell_threshold:
                signal = 'SELL'
            else:
                signal = 'HOLD'
            
            # 7. 收集詳細信息
            latest_price = df_price['Close'].iloc[-1]
            
            details = {
                'symbol': symbol,
                'date': df_price.index[-1].strftime('%Y-%m-%d'),
                'price': float(latest_price),
                'up_probability': float(up_prob),
                'down_probability': float(proba[0]),
                'signal': signal,
                'confidence': float(up_prob) if signal == 'BUY' else float(1 - up_prob)
            }
            
            # 添加前5個最重要的特徵值
            top_features = self.model.get_feature_importance(top_n=5)
            details['top_features'] = {}
            for _, row in top_features.iterrows():
                feat_name = row['feature']
                if feat_name in X.columns:
                    details['top_features'][feat_name] = float(X[feat_name].iloc[0])
            
            print(f"   📊 預測結果:")
            print(f"      當前價格: ${latest_price:.2f}")
            print(f"      上漲概率: {up_prob:.2%}")
            print(f"      信號: {signal} (置信度: {details['confidence']:.2%})")
            
            return signal, up_prob, details
            
        except Exception as e:
            print(f"   ❌ 生成信號時出錯: {str(e)}")
            import traceback
            traceback.print_exc()
            return 'HOLD', 0.0, {'error': str(e)}
    
    def _get_price_data(self, symbol: str, lookback_days: int) -> pd.DataFrame:
        """
        從數據庫獲取價格數據，如果數據庫為空則從 yfinance 獲取
        
        Args:
            symbol: 股票代碼
            lookback_days: 回看天數
            
        Returns:
            價格數據 DataFrame
        """
        from datetime import datetime, timedelta
        
        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=lookback_days)).strftime('%Y-%m-%d')
        
        # 先嘗試從數據庫獲取
        df = self.db.get_market_data(symbol, start_date, end_date)
        
        if not df.empty:
            print(f"   ✅ 從數據庫獲取數據: {len(df)} 條記錄")
            return df
        
        # 如果數據庫為空，從 yfinance 獲取
        print(f"   ⚠️  數據庫無數據，嘗試從 yfinance 獲取...")
        try:
            df = fetch_data(symbol, period=f"{lookback_days}d")
        except (ValueError, Exception) as e:
            print(f"   ❌ yfinance 獲取失敗: {e}")
            return pd.DataFrame()
        
        # 保存到數據庫供下次使用
        if not df.empty:
            self.db.save_market_data(df, symbol)
        
        return df
    
    def _get_macro_data(self) -> pd.DataFrame:
        """從數據庫獲取宏觀數據（委派至 DatabaseAdapter）"""
        try:
            df = self.db.get_macro_data(lookback_years=2)
            if not df.empty:
                print(f"   ✅ 獲取宏觀數據: {len(df)} 條記錄 (已前向填充)")
            else:
                print(f"   ⚠️  無宏觀數據")
            return df
        except Exception as e:
            print(f"   ⚠️  獲取宏觀數據失敗: {str(e)}")
            return pd.DataFrame()
    
    def _get_fundamental_data(self, symbol: str) -> pd.DataFrame:
        """從數據庫獲取基本面數據（委派至 DatabaseAdapter）"""
        try:
            df = self.db.get_fundamental_data(symbol)
            if not df.empty:
                print(f"   ✅ 獲取基本面數據: {len(df)} 條記錄")
            else:
                print(f"   ⚠️  無基本面數據")
            return df
        except Exception as e:
            print(f"   ⚠️  獲取基本面數據失敗: {str(e)}")
            return pd.DataFrame()
    
    def scan_multiple_symbols(self, symbols: list, min_adv_usd: float = 5_000_000) -> pd.DataFrame:
        """
        掃描多個股票並生成信號
        
        包含動態流動性過濾：20日平均成交額 < min_adv_usd 的標的將被排除。
        
        Args:
            symbols: 股票代碼列表
            min_adv_usd: 最小 20 日平均成交額（美元），默認 $5M
            
        Returns:
            包含所有信號的 DataFrame
        """
        print(f"\n🔍 掃描 {len(symbols)} 個股票...")
        
        results = []
        skipped_liquidity = 0
        
        for symbol in symbols:
            # === 流動性過濾 ===
            try:
                df_check = self._get_price_data(symbol, lookback_days=60)
                if not df_check.empty:
                    vol_col = 'Volume' if 'Volume' in df_check.columns else 'volume'
                    if vol_col in df_check.columns:
                        adv = (df_check[vol_col] * df_check['Close']).tail(20).mean()
                        if adv < min_adv_usd:
                            print(f"   ⚠️  {symbol} 流動性不足 (20日 ADV=${adv:,.0f} < ${min_adv_usd:,.0f})，跳過")
                            skipped_liquidity += 1
                            continue
            except Exception:
                pass  # 無法檢查時不阻擋
            
            signal, prob, details = self.generate_signal(symbol)
            
            if 'error' not in details:
                results.append({
                    'symbol': symbol,
                    'signal': signal,
                    'up_probability': prob,
                    'confidence': details['confidence'],
                    'price': details['price'],
                    'date': details['date']
                })
        
        df_results = pd.DataFrame(results)
        
        if not df_results.empty:
            # 按上漲概率排序
            df_results = df_results.sort_values('up_probability', ascending=False)
            
            print(f"\n📊 掃描結果總結:")
            print(f"   BUY 信號: {len(df_results[df_results['signal'] == 'BUY'])}")
            print(f"   SELL 信號: {len(df_results[df_results['signal'] == 'SELL'])}")
            print(f"   HOLD 信號: {len(df_results[df_results['signal'] == 'HOLD'])}")
            if skipped_liquidity > 0:
                print(f"   🚫 流動性不足跳過: {skipped_liquidity} 檔")
        
        return df_results
    
    def backtest_strategy(
        self,
        symbol: str,
        start_date: str,
        end_date: str
    ) -> pd.DataFrame:
        """
        回測策略（簡化版本）
        
        Args:
            symbol: 股票代碼
            start_date: 開始日期
            end_date: 結束日期
            
        Returns:
            包含信號和實際收益的 DataFrame
        """
        print(f"\n📈 回測 {symbol}: {start_date} 到 {end_date}")
        
        # 獲取數據（需要更長的回看期來計算指標）
        from datetime import datetime, timedelta
        start_dt = datetime.strptime(start_date, '%Y-%m-%d')
        extended_start = (start_dt - timedelta(days=365)).strftime('%Y-%m-%d')
        
        df_price = self._get_price_data(symbol, 365 * 3)  # 3年數據
        df_macro = self._get_macro_data()
        df_fundamental = self._get_fundamental_data(symbol)
        
        # 生成特徵（包含基本面數據）
        df_features = make_features(df_price, df_macro, df_fundamental)
        
        # 過濾日期範圍
        df_features = df_features.loc[start_date:end_date]
        
        if df_features.empty:
            print("   ⚠️  回測期間無數據")
            return pd.DataFrame()
        
        # 獲取特徵列
        feature_cols = get_feature_columns(df_features)
        
        # 確保特徵列與模型一致
        for feat in self.model.feature_names:
            if feat not in feature_cols:
                df_features[feat] = 0
        
        X = df_features[self.model.feature_names]
        
        # 預測
        probas = self.model.predict_proba(X)
        df_features['up_probability'] = probas[:, 1]
        
        # 生成信號
        df_features['signal'] = 'HOLD'
        df_features.loc[df_features['up_probability'] >= self.buy_threshold, 'signal'] = 'BUY'
        df_features.loc[df_features['up_probability'] <= self.sell_threshold, 'signal'] = 'SELL'
        
        # 計算實際收益
        df_features['actual_return'] = df_features['Future_Return']
        
        print(f"   ✅ 回測完成: {len(df_features)} 個交易日")
        print(f"   BUY 信號: {len(df_features[df_features['signal'] == 'BUY'])}")
        print(f"   平均預測準確率: {(df_features['Target'] == (df_features['up_probability'] > 0.5).astype(int)).mean():.2%}")
        
        return df_features
    
    def close(self):
        """關閉資源"""
        self.db.close()


def main():
    """測試ML策略"""
    print("=" * 70)
    print(" 🤖 測試 ML 策略")
    print("=" * 70)
    
    try:
        # 初始化策略
        strategy = MLStrategy()
        
        # 測試單個股票
        symbols = ['AAPL', 'MSFT', 'GOOGL']
        
        for symbol in symbols:
            signal, prob, details = strategy.generate_signal(symbol)
            print(f"\n{'='*70}")
        
        # 掃描多個股票
        print(f"\n{'='*70}")
        print(" 📊 批量掃描")
        print("=" * 70)
        df_signals = strategy.scan_multiple_symbols(symbols)
        print("\n", df_signals.to_string(index=False))
        
        strategy.close()
        
    except Exception as e:
        print(f"\n❌ 錯誤: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
