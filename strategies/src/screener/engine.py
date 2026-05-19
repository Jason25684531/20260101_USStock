"""
每日選股引擎 (Daily Screener Engine)

核心流程:
  1. 遍歷股票池, 從 yfinance 取得價格 + 基本面
  2. 對每支股票執行 4 個規則策略篩選
  3. (可選) 呼叫 MLStrategy 取得 ML 信心度
  4. 計算綜合評分 + 支撐壓力
  5. 排名輸出 Top N 推薦
  6. 存入 DB / 推送 Line 通知
"""
import sys
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from pathlib import Path
from datetime import date
from typing import Any, List, Dict, Optional, Tuple

import pandas as pd
import yfinance as yf

# 路徑設定
_SRC_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(_SRC_DIR))

from screener.support_resistance import calc_support_resistance
from screener.market_data_resilience import (
    ERROR_NO_PRICE_DATA,
    STATUS_FALLBACK_SUCCESS,
    STATUS_LIVE_SUCCESS,
    MarketDataFetchResult,
    build_provider_health_summary,
    classify_provider_error,
    is_retryable_status,
)
from config import DEFAULT_SYMBOLS, evaluate_stock_rules_v2
from policies.valuation import GrowthAwarePolicy
from symbol_registry import load_default_active_symbols
from utils.runtime_config import find_existing_model_path


class DailyScreener:
    """每日選股引擎"""

    BUY_PRICE_SUPPORT_WEIGHT = 0.6
    BUY_PRICE_FAIR_VALUE_WEIGHT = 0.4

    @staticmethod
    def _normalize_optional_number(value):
        """將缺失數值正規化為 None，避免 NaN 寫入 DB 失敗。"""
        if value is None:
            return None

        try:
            if pd.isna(value):
                return None
        except TypeError:
            pass

        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _normalize_percentage(cls, value):
        numeric = cls._normalize_optional_number(value)
        if numeric is None:
            return None
        return round(numeric * 100, 4) if numeric <= 1 else round(numeric, 4)

    @classmethod
    def _blend_buy_price(cls, support_1, fair_price, fallback_buy_price):
        normalized_support = cls._normalize_optional_number(support_1)
        normalized_fair_price = cls._normalize_optional_number(fair_price)
        normalized_fallback = cls._normalize_optional_number(fallback_buy_price)

        if normalized_support is not None and normalized_fair_price is not None:
            weighted_price = (
                normalized_support * cls.BUY_PRICE_SUPPORT_WEIGHT
                + normalized_fair_price * cls.BUY_PRICE_FAIR_VALUE_WEIGHT
            )
            return round(weighted_price, 4)

        if normalized_support is not None:
            return round(normalized_support, 4)

        if normalized_fair_price is not None:
            return round(normalized_fair_price, 4)

        return normalized_fallback

    @classmethod
    def _derive_smart_money(cls, info: dict) -> Tuple[Optional[float], str]:
        institutional_ownership = None
        for field in (
            'institutionalOwnership',
            'institutionOwnership',
            'heldPercentInstitutions',
            'inst_ownership_pct',
        ):
            institutional_ownership = cls._normalize_percentage(info.get(field))
            if institutional_ownership is not None:
                break

        insider_sentiment = 'NEUTRAL'
        for field in (
            'netInsiderSharesBuying',
            'netInsiderSharesPurchases',
            'netInsiderPurchases',
            'netSharesPurchases',
        ):
            net_value = cls._normalize_optional_number(info.get(field))
            if net_value is None:
                continue
            if net_value > 0:
                insider_sentiment = 'BUYING'
            elif net_value < 0:
                insider_sentiment = 'SELLING'
            break

        return institutional_ownership, insider_sentiment

    @staticmethod
    def _build_reason_summary(strategy_details: dict, insider_sentiment: str) -> str:
        phrase_map = {
            'breakout': '技術面突破',
            'acceleration': '動能加速',
            'peg': 'PEG低估成長',
            'dupont': '杜邦高品質',
            'institutional': '法人籌碼支持',
            'volume_structure': '量價結構轉強',
            'money_flow': '資金流入改善',
            'multi_tf_momentum': '多週期動能共振',
            'relative_strength': '相對強勢領先',
            'earnings_quality': '盈餘品質穩健',
            'sector_rotation': '產業輪動受惠',
        }

        phrases = []
        for strategy_name, phrase in phrase_map.items():
            strategy_result = strategy_details.get(strategy_name, {})
            if strategy_result.get('pass'):
                phrases.append(phrase)

        if insider_sentiment == 'BUYING':
            phrases.append('🔥內部人買進')
        elif insider_sentiment == 'SELLING':
            phrases.append('內部人偏空調節')

        if not phrases:
            return '綜合訊號中性，待更多確認'

        return ' | '.join(phrases[:5])

    @staticmethod
    def _ensure_column(conn, sql_text, column_name: str, definition_sql: str):
        has_column = conn.execute(sql_text("""
            SELECT COUNT(*)
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'daily_recommendations'
              AND COLUMN_NAME = :column_name
        """), {'column_name': column_name}).scalar()
        if not has_column:
            conn.execute(sql_text(f"ALTER TABLE daily_recommendations ADD COLUMN {definition_sql}"))

    def __init__(
        self,
        symbols: List[str] = None,
        use_ml: bool = None,
        top_n: int = 5,
        delay: float = 0.3,
    ):
        """
        Args:
            symbols: 股票池 (預設 DEFAULT_SYMBOLS)
            use_ml: 是否啟用 ML 信心度加權 (None=自動偵測, True=強制啟用, False=禁用)
            top_n: 輸出 Top N 推薦
            delay: yfinance 請求間隔秒數, 避免限流
        """
        self.symbols = symbols or load_default_active_symbols(fallback_symbols=DEFAULT_SYMBOLS)
        self.top_n = top_n
        self.delay = delay
        self.market_data_retry_count = max(0, int(os.getenv('MARKET_DATA_RETRY_COUNT', '2')))
        self.market_data_timeout_seconds = max(1.0, float(os.getenv('MARKET_DATA_TIMEOUT_SECONDS', '15')))
        self.market_data_retry_backoff_seconds = max(0.0, float(os.getenv('MARKET_DATA_RETRY_BACKOFF_SECONDS', '1')))
        self.market_data_max_age_days = max(0, int(os.getenv('MARKET_DATA_MAX_AGE_DAYS', '3')))
        self.minimum_coverage_ratio = min(
            1.0,
            max(0.0, float(os.getenv('SCREENER_MIN_COVERAGE_RATIO', '0.6'))),
        )
        self._ml_strategy = None
        self._valuation_policy = GrowthAwarePolicy()
        self._fallback_db = None
        self._latest_fetch_results: Dict[str, MarketDataFetchResult] = {}
        self.last_run_summary: Dict[str, Any] = {
            'total_symbols': len(self.symbols),
            'live_successes': 0,
            'fallback_successes': 0,
            'failed_symbols': [],
            'skipped_symbols': [],
            'valid_symbols': 0,
            'coverage_ratio': 0.0,
            'minimum_coverage_ratio': self.minimum_coverage_ratio,
            'recommendations_written': False,
        }
        
        # 自動偵測 ML 模型
        if use_ml is None:
            self.use_ml = find_existing_model_path() is not None
        else:
            self.use_ml = use_ml

        if self.use_ml:
            self._init_ml()

    def _init_ml(self):
        """嘗試載入 ML 模型 (使用共享 MODEL_PATH 規則載入)"""
        try:
            from ml.model import StrategyModel
            from ml.features import make_features, get_feature_columns
            self._ml_model = StrategyModel.load()  # 預設 data/model.pkl
            self._make_features = make_features
            self._get_feature_columns = get_feature_columns
            self._ml_strategy = True  # 標記已載入
            print("✅ ML 模型已載入, 將使用信心度加權評分")
        except Exception as e:
            print(f"⚠️  ML 模型載入失敗, 僅使用規則策略: {e}")
            self._ml_strategy = None
            self._ml_model = None

    def _predict_ml(self, df: pd.DataFrame, info: dict) -> tuple:
        """
        使用已載入的 ML 模型對單支股票進行預測

        Args:
            df: yfinance 價格 DataFrame (至少 60 天)
            info: yfinance ticker.info dict

        Returns:
            (confidence, signal)  — confidence 0~1, signal BUY/SELL/HOLD
        """
        df_feat = self._make_features(df)
        if df_feat.empty:
            return 0.0, 'N/A'

        latest = df_feat.iloc[[-1]]

        # 補齊缺失特徵
        for f in self._ml_model.feature_names:
            if f not in latest.columns:
                latest[f] = 0

        X = latest[self._ml_model.feature_names]
        proba = self._ml_model.predict_proba(X)[0]
        up_prob = float(proba[1])

        if up_prob >= 0.55:
            return up_prob, 'BUY'
        elif up_prob <= 0.3:
            return 0.0, 'SELL'
        return 0.0, 'HOLD'

    # ----------------------------------------------------------
    # 數據獲取
    # ----------------------------------------------------------

    def _get_fallback_db(self):
        if self._fallback_db is None:
            from adapters.database import DatabaseAdapter

            self._fallback_db = DatabaseAdapter()
        return self._fallback_db

    @staticmethod
    def _normalize_price_frame(df: pd.DataFrame) -> pd.DataFrame:
        if df is None or df.empty:
            return df

        normalized = df.copy()
        rename_map = {
            'open': 'Open',
            'high': 'High',
            'low': 'Low',
            'close': 'Close',
            'volume': 'Volume',
            'adj_close': 'Adj Close',
        }
        for source, target in rename_map.items():
            if source in normalized.columns and target not in normalized.columns:
                normalized[target] = normalized[source]
        return normalized

    def _fetch_live_stock_data_once(self, symbol: str) -> Tuple[pd.DataFrame, dict]:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period='1y', interval='1d')
        if df.empty:
            raise ValueError("No price data found")

        info = {}
        try:
            info = ticker.info or {}
        except Exception as exc:
            print(f"    [provider-info-warning] symbol={symbol} provider=yfinance message={exc}")

        return self._normalize_price_frame(df), info

    def _fetch_live_stock_data_with_timeout(self, symbol: str) -> Tuple[pd.DataFrame, dict]:
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(self._fetch_live_stock_data_once, symbol)
        try:
            return future.result(timeout=self.market_data_timeout_seconds)
        except FuturesTimeoutError as exc:
            future.cancel()
            raise TimeoutError(
                f"provider timeout after {self.market_data_timeout_seconds}s"
            ) from exc
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def _load_market_data_fallback(self, symbol: str) -> Tuple[Optional[pd.DataFrame], Optional[int]]:
        df = self._get_fallback_db().get_market_data(symbol)
        if df is None or df.empty:
            return None, None

        normalized = self._normalize_price_frame(df)
        latest_timestamp = pd.to_datetime(normalized.index.max())
        age_days = max(0, (pd.Timestamp(date.today()) - latest_timestamp.normalize()).days)
        return normalized, age_days

    def _store_fetch_result(self, result: MarketDataFetchResult) -> MarketDataFetchResult:
        self._latest_fetch_results[result.symbol] = result
        return result

    def fetch_stock_data_result(self, symbol: str) -> MarketDataFetchResult:
        max_attempts = max(1, self.market_data_retry_count + 1)
        last_status = ERROR_NO_PRICE_DATA
        last_message = "No price data found"

        for attempt in range(1, max_attempts + 1):
            try:
                df, info = self._fetch_live_stock_data_with_timeout(symbol)
                return self._store_fetch_result(MarketDataFetchResult(
                    symbol=symbol,
                    status=STATUS_LIVE_SUCCESS,
                    message='live provider success',
                    df=df,
                    info=info,
                    attempts=attempt,
                ))
            except Exception as exc:
                last_status = classify_provider_error(exc)
                last_message = str(exc)
                print(
                    f"  [provider-error] symbol={symbol} provider=yfinance "
                    f"status={last_status} attempt={attempt}/{max_attempts} message={last_message}"
                )

                if attempt < max_attempts and is_retryable_status(last_status):
                    if self.market_data_retry_backoff_seconds > 0:
                        time.sleep(self.market_data_retry_backoff_seconds)
                    continue
                break

        fallback_df, cache_age_days = self._load_market_data_fallback(symbol)
        if fallback_df is not None and cache_age_days is not None:
            if cache_age_days <= self.market_data_max_age_days:
                print(
                    f"  [provider-fallback] symbol={symbol} provider=market_data "
                    f"status={STATUS_FALLBACK_SUCCESS} cache_age_days={cache_age_days}"
                )
                return self._store_fetch_result(MarketDataFetchResult(
                    symbol=symbol,
                    provider='market_data',
                    status=STATUS_FALLBACK_SUCCESS,
                    message=f'using market_data fallback age={cache_age_days}d',
                    df=fallback_df,
                    info={},
                    attempts=max_attempts,
                    used_fallback=True,
                    cache_age_days=cache_age_days,
                ))

            print(
                f"  [provider-fallback-rejected] symbol={symbol} provider=market_data "
                f"status={last_status} cache_age_days={cache_age_days}"
            )
            last_message = f"{last_message}; stale fallback age={cache_age_days}d"

        return self._store_fetch_result(MarketDataFetchResult(
            symbol=symbol,
            status=last_status,
            message=last_message,
            attempts=max_attempts,
            used_fallback=False,
            cache_age_days=cache_age_days,
        ))

    def fetch_stock_data(self, symbol: str) -> Tuple[Optional[pd.DataFrame], dict]:
        result = self.fetch_stock_data_result(symbol)
        return result.df, result.info
        """
        從 yfinance 獲取一支股票的價格 + 基本面數據

        Returns:
            (df_price, info_dict)  —  df_price 可能為 None
        """
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period='1y', interval='1d')
            if df.empty:
                return None, {}
            info = ticker.info or {}
            return df, info
        except Exception as e:
            print(f"  ⚠️  {symbol} 數據獲取失敗: {e}")
            return None, {}

    # ----------------------------------------------------------
    # 單股評估
    # ----------------------------------------------------------

    def evaluate_stock(self, symbol: str) -> Optional[Dict]:
        """
        對單支股票執行全部篩選策略 + 支撐壓力

        Returns:
            評估結果 dict, 或 None (數據不足)
        """
        df, info = self.fetch_stock_data(symbol)
        if df is None or len(df) < 60:
            return None

        # --- Yahoo Fallback: 補齊 PEG / ROE ---
        fetch_result = self._latest_fetch_results.get(symbol)
        if (
            fetch_result
            and fetch_result.status == STATUS_LIVE_SUCCESS
            and not info.get('pegRatio')
            and not info.get('trailingPegRatio')
        ):
            try:
                fresh = yf.Ticker(symbol).info or {}
                for k in ('pegRatio', 'trailingPegRatio', 'returnOnEquity',
                          'priceToBook', 'trailingPE', 'operatingCashflow',
                          'totalRevenue', 'totalAssets'):
                    if fresh.get(k) is not None and info.get(k) is None:
                        info[k] = fresh[k]
            except Exception:
                pass
        target_price = self._normalize_optional_number(info.get('targetMeanPrice'))
        institutional_ownership, insider_sentiment = self._derive_smart_money(info)

        close_col = 'Close' if 'Close' in df.columns else 'close'
        current_price = float(df[close_col].iloc[-1])
        eps_ttm = self._normalize_optional_number(
            info.get('trailingEps')
            or info.get('epsTrailingTwelveMonths')
            or info.get('epsCurrentYear')
        )
        revenue_growth_yoy = self._normalize_optional_number(
            info.get('revenueGrowth')
            or info.get('revenue_growth_yoy')
            or info.get('revenue_growth')
        )
        valuation = self._valuation_policy.evaluate(
            current_price=current_price,
            eps_ttm=eps_ttm,
            revenue_growth_yoy=revenue_growth_yoy,
        )

        # --- 全策略評估（v2 Registry 版本）---
        eval_result = evaluate_stock_rules_v2(df, info, symbol=symbol)
        if eval_result is None:
            return None

        r_breakout = eval_result.get('breakout', {"pass": False, "score": 0, "details": "N/A"})
        r_accel = eval_result.get('acceleration', {"pass": False, "score": 0, "details": "N/A"})
        r_peg = eval_result.get('peg', {"pass": False, "score": 0, "details": "N/A"})
        r_dupont = eval_result.get('dupont', {"pass": False, "score": 0, "details": "N/A"})
        rule_score = eval_result['rule_score']
        passes = eval_result['passes']
        total_strategies = eval_result.get('total_strategies', 4)
        all_results = eval_result.get('all_results', {})

        # --- ML 信心度 (可選) ---
        ml_conf = 0.0
        ml_signal = 'N/A'
        if self._ml_strategy and self._ml_model:
            try:
                ml_conf, ml_signal = self._predict_ml(df, info)
            except Exception as e:
                print(f"    ⚠️ ML 預測失敗: {e}")

        # --- 綜合評分 ---
        if ml_conf > 0:
            # Rating = Raw_Score * (Confidence / 0.5)
            confidence_factor = ml_conf / 0.5
            total_score = rule_score * confidence_factor
        else:
            total_score = rule_score  # 0 ~ 4

        # --- 支撐壓力 ---
        sr = calc_support_resistance(df)
        support_1 = self._normalize_optional_number(sr.get('support_1')) if isinstance(sr, dict) else None

        valuation['buy_price'] = self._blend_buy_price(
            support_1=support_1,
            fair_price=valuation.get('fair_price'),
            fallback_buy_price=valuation.get('buy_price'),
        )

        # --- 信號判定 ---
        # BUY: 至少 30% 策略通過 或 總分 >= 策略數的 20%
        min_passes = max(2, total_strategies * 0.3)
        min_score = max(2.0, total_strategies * 0.2)
        signal_type = 'BUY' if passes >= min_passes or total_score >= min_score else 'SELL'

        return {
            'symbol': symbol,
            'signal': signal_type,
            'total_score': round(total_score, 2),
            'current_price': round(current_price, 2),
            'target_price': target_price,
            'institutional_ownership': institutional_ownership,
            'insider_sentiment': insider_sentiment,
            'breakout': r_breakout,
            'acceleration': r_accel,
            'peg': r_peg,
            'dupont': r_dupont,
            'ml_confidence': round(ml_conf, 3),
            'ml_signal': ml_signal,
            'support_resistance': sr,
            'pe_ratio': info.get('trailingPE'),
            'peg_ratio': info.get('pegRatio') or info.get('trailingPegRatio'),
            'pb_ratio': info.get('priceToBook'),
            'roe': info.get('returnOnEquity'),
            'revenue_growth_yoy': revenue_growth_yoy,
            'fair_price': valuation.get('fair_price'),
            'buy_price': valuation.get('buy_price'),
            'sell_price': valuation.get('sell_price'),
            'valuation_status': valuation.get('valuation_status', 'FAIR'),
            'passes': passes,
            'total_strategies': total_strategies,
            'all_results': all_results,
        }

    # ----------------------------------------------------------
    # 批量掃描
    # ----------------------------------------------------------

    def scan_all(self) -> pd.DataFrame:
        """
        掃描整個股票池

        Returns:
            DataFrame with all evaluation results, sorted by total_score DESC
        """
        print(f"\n{'='*70}")
        print(f"  🔍 每日選股掃描 — {date.today()}")
        print(f"  股票池: {len(self.symbols)} 支")
        print(f"  ML 加權: {'✅' if self._ml_strategy else '❌'}")
        print(f"{'='*70}\n")

        results = []
        summary = {
            'total_symbols': len(self.symbols),
            'live_successes': 0,
            'fallback_successes': 0,
            'failed_symbols': [],
            'skipped_symbols': [],
            'valid_symbols': 0,
            'coverage_ratio': 0.0,
            'minimum_coverage_ratio': self.minimum_coverage_ratio,
            'recommendations_written': False,
        }
        self._latest_fetch_results = {}
        for i, symbol in enumerate(self.symbols, 1):
            print(f"[{i}/{len(self.symbols)}] {symbol} ...", end=" ")
            result = self.evaluate_stock(symbol)
            fetch_result = self._latest_fetch_results.get(symbol)
            if fetch_result:
                if fetch_result.status == STATUS_LIVE_SUCCESS:
                    summary['live_successes'] += 1
                elif fetch_result.status == STATUS_FALLBACK_SUCCESS:
                    summary['fallback_successes'] += 1
                else:
                    summary['failed_symbols'].append({
                        'symbol': symbol,
                        'status': fetch_result.status,
                        'message': fetch_result.message,
                    })

                if fetch_result.df is not None and len(fetch_result.df) >= 60:
                    summary['valid_symbols'] += 1
                else:
                    summary['skipped_symbols'].append({
                        'symbol': symbol,
                        'status': fetch_result.status,
                        'message': fetch_result.message,
                    })
            if result:
                results.append(result)
                print(f"✅ score={result['total_score']:.2f} "
                      f"passes={result['passes']}/4 "
                      f"signal={result['signal']}")
            else:
                print("⚠️ 跳過 (數據不足)")

            if self.delay > 0 and i < len(self.symbols):
                time.sleep(self.delay)

        if summary['total_symbols'] > 0:
            summary['coverage_ratio'] = summary['valid_symbols'] / summary['total_symbols']
        summary['provider_health_summary'] = build_provider_health_summary(summary)
        self.last_run_summary = summary
        print(summary['provider_health_summary'])

        if not results:
            print("❌ 無有效結果")
            return pd.DataFrame()

        df = pd.DataFrame(results)
        df = df.sort_values('total_score', ascending=False).reset_index(drop=True)
        return df

    # ----------------------------------------------------------
    # Top N 推薦
    # ----------------------------------------------------------

    def get_top_recommendations(self, df_all: pd.DataFrame = None, n: int = None) -> List[Dict]:
        """
        取得 Top N 推薦

        Args:
            df_all: scan_all() 的結果, 或 None (自動掃描)
            n: 推薦數量 (預設 self.top_n)

        Returns:
            List of recommendation dicts
        """
        if df_all is None:
            df_all = self.scan_all()

        n = n or self.top_n
        top = df_all.head(n)

        recommendations = []
        for rank, (_, row) in enumerate(top.iterrows(), 1):
            strategy_details = row.get('all_results') or {
                'breakout': row['breakout'],
                'acceleration': row['acceleration'],
                'peg': row['peg'],
                'dupont': row['dupont'],
            }
            insider_sentiment = str(row.get('insider_sentiment') or 'NEUTRAL').upper()
            rec = {
                'rank': rank,
                'symbol': row['symbol'],
                'signal': row['signal'],
                'total_score': row['total_score'],
                'current_price': row['current_price'],
                'target_price': self._normalize_optional_number(row.get('target_price')),
                'institutional_ownership': self._normalize_percentage(row.get('institutional_ownership')),
                'insider_sentiment': insider_sentiment,
                'breakout_pass': row['breakout']['pass'],
                'acceleration_pass': row['acceleration']['pass'],
                'peg_pass': row['peg']['pass'],
                'dupont_pass': row['dupont']['pass'],
                'ml_confidence': row.get('ml_confidence', 0),
                'support_1': row['support_resistance'].get('support_1'),
                'support_2': row['support_resistance'].get('support_2'),
                'resistance_1': row['support_resistance'].get('resistance_1'),
                'resistance_2': row['support_resistance'].get('resistance_2'),
                'pe_ratio': row.get('pe_ratio'),
                'peg_ratio': row.get('peg_ratio'),
                'pb_ratio': row.get('pb_ratio'),
                'roe': row.get('roe'),
                'fair_price': self._normalize_optional_number(row.get('fair_price')),
                'buy_price': self._normalize_optional_number(row.get('buy_price')),
                'sell_price': self._normalize_optional_number(row.get('sell_price')),
                'valuation_status': str(row.get('valuation_status') or 'FAIR').upper(),
                'strategy_details': strategy_details,
            }
            rec['reason_summary'] = self._build_reason_summary(strategy_details, insider_sentiment)
            recommendations.append(rec)

        return recommendations

    # ----------------------------------------------------------
    # DB 儲存
    # ----------------------------------------------------------

    def _can_write_recommendations(self, recommendations: List[Dict]) -> Tuple[bool, str]:
        summary = self.last_run_summary or {}
        coverage_ratio = float(summary.get('coverage_ratio', 0.0) or 0.0)
        minimum_ratio = float(summary.get('minimum_coverage_ratio', self.minimum_coverage_ratio) or 0.0)

        if not recommendations:
            return False, 'no recommendations generated'

        if coverage_ratio < minimum_ratio:
            return False, (
                f'insufficient coverage_ratio={coverage_ratio:.2f} '
                f'minimum_coverage_ratio={minimum_ratio:.2f}'
            )

        return True, 'coverage threshold met'

    def _save_to_db_legacy(self, recommendations: List[Dict], scan_date: date = None):
        can_write, reason = self._can_write_recommendations(recommendations)
        if not can_write:
            self.last_run_summary['recommendations_written'] = False
            self.last_run_summary['write_blocked_reason'] = reason
            self.last_run_summary['provider_health_summary'] = build_provider_health_summary(self.last_run_summary)
            print(f"[screener-write-skipped] reason={reason}")
            print(self.last_run_summary['provider_health_summary'])
            return False
        """
        將推薦結果寫入 daily_recommendations 表

        Args:
            recommendations: get_top_recommendations() 的結果
            scan_date: 掃描日期 (預設今天)
        """
        from adapters.database import DatabaseAdapter

        scan_date = scan_date or date.today()
        db = DatabaseAdapter()

        try:
            # 確保表存在
            from sqlalchemy import text as sql_text
            with db.engine.connect() as conn:
                conn.execute(sql_text("""
                    CREATE TABLE IF NOT EXISTS daily_recommendations (
                        id BIGINT AUTO_INCREMENT PRIMARY KEY,
                        scan_date DATE NOT NULL,
                        symbol VARCHAR(10) NOT NULL,
                        rank_position INT NOT NULL,
                        signal_type VARCHAR(4) NOT NULL DEFAULT 'BUY',
                        total_score DECIMAL(4,2) NOT NULL,
                        breakout_pass TINYINT(1) DEFAULT 0,
                        acceleration_pass TINYINT(1) DEFAULT 0,
                        peg_pass TINYINT(1) DEFAULT 0,
                        dupont_pass TINYINT(1) DEFAULT 0,
                        ml_confidence DECIMAL(4,3) DEFAULT NULL,
                        current_price DECIMAL(12,4) NOT NULL,
                        target_price DECIMAL(12,4),
                        institutional_ownership DECIMAL(10,4),
                        insider_sentiment VARCHAR(16) DEFAULT 'NEUTRAL',
                        support_1 DECIMAL(12,4),
                        support_2 DECIMAL(12,4),
                        resistance_1 DECIMAL(12,4),
                        resistance_2 DECIMAL(12,4),
                        pe_ratio DECIMAL(10,2),
                        peg_ratio DECIMAL(10,4),
                        pb_ratio DECIMAL(10,2),
                        roe DECIMAL(10,4),
                        fair_price DECIMAL(12,4),
                        buy_price DECIMAL(12,4),
                        sell_price DECIMAL(12,4),
                        valuation_status VARCHAR(16) DEFAULT 'FAIR',
                        reason_summary TEXT,
                        strategy_details JSON,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE KEY uk_date_symbol (scan_date, symbol),
                        INDEX idx_scan_date (scan_date)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """))

                missing_columns = [
                    ('target_price', 'target_price DECIMAL(12,4) NULL AFTER current_price'),
                    ('institutional_ownership', 'institutional_ownership DECIMAL(10,4) NULL AFTER target_price'),
                    ('insider_sentiment', "insider_sentiment VARCHAR(16) NULL DEFAULT 'NEUTRAL' AFTER institutional_ownership"),
                    ('fair_price', 'fair_price DECIMAL(12,4) NULL AFTER roe'),
                    ('buy_price', 'buy_price DECIMAL(12,4) NULL AFTER fair_price'),
                    ('sell_price', 'sell_price DECIMAL(12,4) NULL AFTER buy_price'),
                    ('valuation_status', "valuation_status VARCHAR(16) NULL DEFAULT 'FAIR' AFTER sell_price"),
                    ('reason_summary', 'reason_summary TEXT NULL AFTER valuation_status'),
                ]
                for column_name, definition_sql in missing_columns:
                    self._ensure_column(conn, sql_text, column_name, definition_sql)
                conn.commit()
            self.last_run_summary['recommendations_written'] = True
            self.last_run_summary['write_blocked_reason'] = None
            self.last_run_summary['provider_health_summary'] = build_provider_health_summary(self.last_run_summary)
            print(f"[screener-write-complete] recommendations={len(recommendations)} scan_date={scan_date}")
            print(self.last_run_summary['provider_health_summary'])
            return True

            # 寫入推薦結果 (UPSERT)
            with db.engine.connect() as conn:
                for rec in recommendations:
                    safe_float = self._normalize_optional_number
                    conn.execute(sql_text("""
                        INSERT INTO daily_recommendations
                            (scan_date, symbol, rank_position, signal_type, total_score,
                             breakout_pass, acceleration_pass, peg_pass, dupont_pass,
                                      ml_confidence, current_price, target_price,
                                      institutional_ownership, insider_sentiment,
                             support_1, support_2, resistance_1, resistance_2,
                                      pe_ratio, peg_ratio, pb_ratio, roe,
                                      fair_price, buy_price, sell_price, valuation_status,
                                      reason_summary, strategy_details)
                        VALUES
                            (:scan_date, :symbol, :rank, :signal, :score,
                             :bp, :ap, :pp, :dp,
                                      :ml, :price, :target_price,
                                      :institutional_ownership, :insider_sentiment,
                             :s1, :s2, :r1, :r2,
                                      :pe, :peg, :pb, :roe,
                                      :fair_price, :buy_price, :sell_price, :valuation_status,
                                      :reason_summary, :details)
                        ON DUPLICATE KEY UPDATE
                            rank_position = VALUES(rank_position),
                            signal_type = VALUES(signal_type),
                            total_score = VALUES(total_score),
                            breakout_pass = VALUES(breakout_pass),
                            acceleration_pass = VALUES(acceleration_pass),
                            peg_pass = VALUES(peg_pass),
                            dupont_pass = VALUES(dupont_pass),
                            ml_confidence = VALUES(ml_confidence),
                            current_price = VALUES(current_price),
                            target_price = VALUES(target_price),
                            institutional_ownership = VALUES(institutional_ownership),
                            insider_sentiment = VALUES(insider_sentiment),
                            support_1 = VALUES(support_1),
                            support_2 = VALUES(support_2),
                            resistance_1 = VALUES(resistance_1),
                            resistance_2 = VALUES(resistance_2),
                            pe_ratio = VALUES(pe_ratio),
                            peg_ratio = VALUES(peg_ratio),
                            pb_ratio = VALUES(pb_ratio),
                            roe = VALUES(roe),
                                fair_price = VALUES(fair_price),
                                buy_price = VALUES(buy_price),
                                sell_price = VALUES(sell_price),
                                valuation_status = VALUES(valuation_status),
                                reason_summary = VALUES(reason_summary),
                            strategy_details = VALUES(strategy_details)
                    """), {
                        'scan_date': str(scan_date),
                        'symbol': rec['symbol'],
                        'rank': rec['rank'],
                        'signal': rec['signal'],
                        'score': rec['total_score'],
                        'bp': int(rec['breakout_pass']),
                        'ap': int(rec['acceleration_pass']),
                        'pp': int(rec['peg_pass']),
                        'dp': int(rec['dupont_pass']),
                        'ml': safe_float(rec.get('ml_confidence')),
                        'price': safe_float(rec.get('current_price')),
                        'target_price': safe_float(rec.get('target_price')),
                        'institutional_ownership': self._normalize_percentage(rec.get('institutional_ownership')),
                        'insider_sentiment': str(rec.get('insider_sentiment') or 'NEUTRAL').upper(),
                        's1': safe_float(rec.get('support_1')),
                        's2': safe_float(rec.get('support_2')),
                        'r1': safe_float(rec.get('resistance_1')),
                        'r2': safe_float(rec.get('resistance_2')),
                        'pe': safe_float(rec.get('pe_ratio')),
                        'peg': safe_float(rec.get('peg_ratio')),
                        'pb': safe_float(rec.get('pb_ratio')),
                        'roe': safe_float(rec.get('roe')),
                        'fair_price': safe_float(rec.get('fair_price')),
                        'buy_price': safe_float(rec.get('buy_price')),
                        'sell_price': safe_float(rec.get('sell_price')),
                        'valuation_status': str(rec.get('valuation_status') or 'FAIR').upper(),
                        'reason_summary': str(rec.get('reason_summary') or '綜合訊號中性，待更多確認'),
                        'details': json.dumps(rec.get('strategy_details', {}),
                                              ensure_ascii=False, default=str),
                    })
                conn.commit()

            print(f"✅ 已存入 {len(recommendations)} 筆推薦至 DB (scan_date={scan_date})")

        except Exception as e:
            print(f"⚠️  DB 寫入失敗: {e}")
        finally:
            db.close()

    # ----------------------------------------------------------
    # Line 通知格式化
    # ----------------------------------------------------------

    def save_to_db(self, recommendations: List[Dict], scan_date: date = None):
        can_write, reason = self._can_write_recommendations(recommendations)
        if not can_write:
            self.last_run_summary['recommendations_written'] = False
            self.last_run_summary['write_blocked_reason'] = reason
            self.last_run_summary['provider_health_summary'] = build_provider_health_summary(self.last_run_summary)
            print(f"[screener-write-skipped] reason={reason}")
            print(self.last_run_summary['provider_health_summary'])
            return False

        from adapters.database import DatabaseAdapter
        from sqlalchemy import text as sql_text

        scan_date = scan_date or date.today()
        db = DatabaseAdapter()

        try:
            with db.engine.connect() as conn:
                conn.execute(sql_text("""
                    CREATE TABLE IF NOT EXISTS daily_recommendations (
                        id BIGINT AUTO_INCREMENT PRIMARY KEY,
                        scan_date DATE NOT NULL,
                        symbol VARCHAR(10) NOT NULL,
                        rank_position INT NOT NULL,
                        signal_type VARCHAR(4) NOT NULL DEFAULT 'BUY',
                        total_score DECIMAL(4,2) NOT NULL,
                        breakout_pass TINYINT(1) DEFAULT 0,
                        acceleration_pass TINYINT(1) DEFAULT 0,
                        peg_pass TINYINT(1) DEFAULT 0,
                        dupont_pass TINYINT(1) DEFAULT 0,
                        ml_confidence DECIMAL(4,3) DEFAULT NULL,
                        current_price DECIMAL(12,4) NOT NULL,
                        target_price DECIMAL(12,4),
                        institutional_ownership DECIMAL(10,4),
                        insider_sentiment VARCHAR(16) DEFAULT 'NEUTRAL',
                        support_1 DECIMAL(12,4),
                        support_2 DECIMAL(12,4),
                        resistance_1 DECIMAL(12,4),
                        resistance_2 DECIMAL(12,4),
                        pe_ratio DECIMAL(10,2),
                        peg_ratio DECIMAL(10,4),
                        pb_ratio DECIMAL(10,2),
                        roe DECIMAL(10,4),
                        fair_price DECIMAL(12,4),
                        buy_price DECIMAL(12,4),
                        sell_price DECIMAL(12,4),
                        valuation_status VARCHAR(16) DEFAULT 'FAIR',
                        reason_summary TEXT,
                        strategy_details JSON,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE KEY uk_date_symbol (scan_date, symbol),
                        INDEX idx_scan_date (scan_date)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """))

                missing_columns = [
                    ('target_price', 'target_price DECIMAL(12,4) NULL AFTER current_price'),
                    ('institutional_ownership', 'institutional_ownership DECIMAL(10,4) NULL AFTER target_price'),
                    ('insider_sentiment', "insider_sentiment VARCHAR(16) NULL DEFAULT 'NEUTRAL' AFTER institutional_ownership"),
                    ('fair_price', 'fair_price DECIMAL(12,4) NULL AFTER roe'),
                    ('buy_price', 'buy_price DECIMAL(12,4) NULL AFTER fair_price'),
                    ('sell_price', 'sell_price DECIMAL(12,4) NULL AFTER buy_price'),
                    ('valuation_status', "valuation_status VARCHAR(16) NULL DEFAULT 'FAIR' AFTER sell_price"),
                    ('reason_summary', 'reason_summary TEXT NULL AFTER valuation_status'),
                ]
                for column_name, definition_sql in missing_columns:
                    self._ensure_column(conn, sql_text, column_name, definition_sql)
                conn.commit()

            with db.engine.connect() as conn:
                for rec in recommendations:
                    safe_float = self._normalize_optional_number
                    conn.execute(sql_text("""
                        INSERT INTO daily_recommendations
                            (scan_date, symbol, rank_position, signal_type, total_score,
                             breakout_pass, acceleration_pass, peg_pass, dupont_pass,
                             ml_confidence, current_price, target_price,
                             institutional_ownership, insider_sentiment,
                             support_1, support_2, resistance_1, resistance_2,
                             pe_ratio, peg_ratio, pb_ratio, roe,
                             fair_price, buy_price, sell_price, valuation_status,
                             reason_summary, strategy_details)
                        VALUES
                            (:scan_date, :symbol, :rank, :signal, :score,
                             :bp, :ap, :pp, :dp,
                             :ml, :price, :target_price,
                             :institutional_ownership, :insider_sentiment,
                             :s1, :s2, :r1, :r2,
                             :pe, :peg, :pb, :roe,
                             :fair_price, :buy_price, :sell_price, :valuation_status,
                             :reason_summary, :details)
                        ON DUPLICATE KEY UPDATE
                            rank_position = VALUES(rank_position),
                            signal_type = VALUES(signal_type),
                            total_score = VALUES(total_score),
                            breakout_pass = VALUES(breakout_pass),
                            acceleration_pass = VALUES(acceleration_pass),
                            peg_pass = VALUES(peg_pass),
                            dupont_pass = VALUES(dupont_pass),
                            ml_confidence = VALUES(ml_confidence),
                            current_price = VALUES(current_price),
                            target_price = VALUES(target_price),
                            institutional_ownership = VALUES(institutional_ownership),
                            insider_sentiment = VALUES(insider_sentiment),
                            support_1 = VALUES(support_1),
                            support_2 = VALUES(support_2),
                            resistance_1 = VALUES(resistance_1),
                            resistance_2 = VALUES(resistance_2),
                            pe_ratio = VALUES(pe_ratio),
                            peg_ratio = VALUES(peg_ratio),
                            pb_ratio = VALUES(pb_ratio),
                            roe = VALUES(roe),
                            fair_price = VALUES(fair_price),
                            buy_price = VALUES(buy_price),
                            sell_price = VALUES(sell_price),
                            valuation_status = VALUES(valuation_status),
                            reason_summary = VALUES(reason_summary),
                            strategy_details = VALUES(strategy_details)
                    """), {
                        'scan_date': str(scan_date),
                        'symbol': rec['symbol'],
                        'rank': rec['rank'],
                        'signal': rec['signal'],
                        'score': rec['total_score'],
                        'bp': int(rec['breakout_pass']),
                        'ap': int(rec['acceleration_pass']),
                        'pp': int(rec['peg_pass']),
                        'dp': int(rec['dupont_pass']),
                        'ml': safe_float(rec.get('ml_confidence')),
                        'price': safe_float(rec.get('current_price')),
                        'target_price': safe_float(rec.get('target_price')),
                        'institutional_ownership': self._normalize_percentage(rec.get('institutional_ownership')),
                        'insider_sentiment': str(rec.get('insider_sentiment') or 'NEUTRAL').upper(),
                        's1': safe_float(rec.get('support_1')),
                        's2': safe_float(rec.get('support_2')),
                        'r1': safe_float(rec.get('resistance_1')),
                        'r2': safe_float(rec.get('resistance_2')),
                        'pe': safe_float(rec.get('pe_ratio')),
                        'peg': safe_float(rec.get('peg_ratio')),
                        'pb': safe_float(rec.get('pb_ratio')),
                        'roe': safe_float(rec.get('roe')),
                        'fair_price': safe_float(rec.get('fair_price')),
                        'buy_price': safe_float(rec.get('buy_price')),
                        'sell_price': safe_float(rec.get('sell_price')),
                        'valuation_status': str(rec.get('valuation_status') or 'FAIR').upper(),
                        'reason_summary': str(rec.get('reason_summary') or 'No summary available'),
                        'details': json.dumps(rec.get('strategy_details', {}), ensure_ascii=False, default=str),
                    })
                conn.commit()

            self.last_run_summary['recommendations_written'] = True
            self.last_run_summary['write_blocked_reason'] = None
            self.last_run_summary['provider_health_summary'] = build_provider_health_summary(self.last_run_summary)
            print(f"[screener-write-complete] recommendations={len(recommendations)} scan_date={scan_date}")
            print(self.last_run_summary['provider_health_summary'])
            return True
        except Exception as e:
            print(f"DB write failed: {e}")
            self.last_run_summary['recommendations_written'] = False
            self.last_run_summary['write_blocked_reason'] = str(e)
            self.last_run_summary['provider_health_summary'] = build_provider_health_summary(self.last_run_summary)
            return False
        finally:
            db.close()

    def format_line_message(self, recommendations: List[Dict]) -> str:
        """
        格式化 Line 推送訊息

        Returns:
            格式化的純文字訊息
        """
        lines = [
            f"📊 每日選股推薦 — {date.today().strftime('%Y/%m/%d')}",
            f"{'─' * 30}",
        ]

        for rec in recommendations:
            emoji = '🟢' if rec['signal'] == 'BUY' else '🔴'
            strats = []
            if rec['breakout_pass']:
                strats.append('突破')
            if rec['acceleration_pass']:
                strats.append('加速')
            if rec['peg_pass']:
                strats.append('PEG')
            if rec['dupont_pass']:
                strats.append('杜邦')

            lines.append(
                f"\n{emoji} #{rec['rank']} {rec['symbol']}  "
                f"${rec['current_price']:.2f}  "
                f"評分:{rec['total_score']:.1f}/5"
            )
            lines.append(f"   策略: {'+'.join(strats) if strats else '—'}")

            s1 = rec.get('support_1')
            r1 = rec.get('resistance_1')
            if s1 and r1:
                lines.append(f"   支撐: ${s1:.2f}  壓力: ${r1:.2f}")

            pe = rec.get('pe_ratio')
            peg = rec.get('peg_ratio')
            if pe is not None:
                lines.append(f"   PE:{pe:.1f}" + (f"  PEG:{peg:.2f}" if peg else ""))

        lines.append(f"\n{'─' * 30}")
        lines.append(f"共掃描 {len(self.symbols)} 支, 推薦 {len(recommendations)} 支")
        return "\n".join(lines)

    # ----------------------------------------------------------
    # 資源清理
    # ----------------------------------------------------------

    def close(self):
        """關閉資源"""
        if self._ml_strategy:
            try:
                self._ml_strategy.close()
            except Exception:
                pass
