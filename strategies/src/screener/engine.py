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
import time
from pathlib import Path
from datetime import date
from typing import List, Dict, Optional, Tuple

import pandas as pd
import yfinance as yf

# 路徑設定
_SRC_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(_SRC_DIR))

from screener.support_resistance import calc_support_resistance
from config import DEFAULT_SYMBOLS, evaluate_stock_rules_v2


class DailyScreener:
    """每日選股引擎"""

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
        self.symbols = symbols or DEFAULT_SYMBOLS
        self.top_n = top_n
        self.delay = delay
        self._ml_strategy = None
        
        # 自動偵測 ML 模型
        if use_ml is None:
            # 若 data/model.pkl 或 data/test_model.pkl 存在，自動啟用 ML
            data_dir = Path(__file__).parent.parent.parent / 'data'
            model_path = data_dir / 'model.pkl'
            test_model_path = data_dir / 'test_model.pkl'
            self.use_ml = model_path.exists() or test_model_path.exists()
        else:
            self.use_ml = use_ml

        if self.use_ml:
            self._init_ml()

    def _init_ml(self):
        """嘗試載入 ML 模型 (從 data/model.pkl，若不存在則降級)"""
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

    def fetch_stock_data(self, symbol: str) -> Tuple[Optional[pd.DataFrame], dict]:
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
        if not info.get('pegRatio') and not info.get('trailingPegRatio'):
            try:
                fresh = yf.Ticker(symbol).info or {}
                for k in ('pegRatio', 'trailingPegRatio', 'returnOnEquity',
                          'priceToBook', 'trailingPE', 'operatingCashflow',
                          'totalRevenue', 'totalAssets'):
                    if fresh.get(k) is not None and info.get(k) is None:
                        info[k] = fresh[k]
            except Exception:
                pass

        close_col = 'Close' if 'Close' in df.columns else 'close'
        current_price = float(df[close_col].iloc[-1])

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
        for i, symbol in enumerate(self.symbols, 1):
            print(f"[{i}/{len(self.symbols)}] {symbol} ...", end=" ")
            result = self.evaluate_stock(symbol)
            if result:
                results.append(result)
                print(f"✅ score={result['total_score']:.2f} "
                      f"passes={result['passes']}/4 "
                      f"signal={result['signal']}")
            else:
                print("⚠️ 跳過 (數據不足)")

            if self.delay > 0 and i < len(self.symbols):
                time.sleep(self.delay)

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
            rec = {
                'rank': rank,
                'symbol': row['symbol'],
                'signal': row['signal'],
                'total_score': row['total_score'],
                'current_price': row['current_price'],
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
                'strategy_details': {
                    'breakout': row['breakout'],
                    'acceleration': row['acceleration'],
                    'peg': row['peg'],
                    'dupont': row['dupont'],
                },
            }
            recommendations.append(rec)

        return recommendations

    # ----------------------------------------------------------
    # DB 儲存
    # ----------------------------------------------------------

    def save_to_db(self, recommendations: List[Dict], scan_date: date = None):
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
                        support_1 DECIMAL(12,4),
                        support_2 DECIMAL(12,4),
                        resistance_1 DECIMAL(12,4),
                        resistance_2 DECIMAL(12,4),
                        pe_ratio DECIMAL(10,2),
                        peg_ratio DECIMAL(10,4),
                        pb_ratio DECIMAL(10,2),
                        roe DECIMAL(10,4),
                        strategy_details JSON,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE KEY uk_date_symbol (scan_date, symbol),
                        INDEX idx_scan_date (scan_date)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """))
                conn.commit()

            # 寫入推薦結果 (UPSERT)
            with db.engine.connect() as conn:
                for rec in recommendations:
                    conn.execute(sql_text("""
                        INSERT INTO daily_recommendations
                            (scan_date, symbol, rank_position, signal_type, total_score,
                             breakout_pass, acceleration_pass, peg_pass, dupont_pass,
                             ml_confidence, current_price,
                             support_1, support_2, resistance_1, resistance_2,
                             pe_ratio, peg_ratio, pb_ratio, roe, strategy_details)
                        VALUES
                            (:scan_date, :symbol, :rank, :signal, :score,
                             :bp, :ap, :pp, :dp,
                             :ml, :price,
                             :s1, :s2, :r1, :r2,
                             :pe, :peg, :pb, :roe, :details)
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
                            support_1 = VALUES(support_1),
                            support_2 = VALUES(support_2),
                            resistance_1 = VALUES(resistance_1),
                            resistance_2 = VALUES(resistance_2),
                            pe_ratio = VALUES(pe_ratio),
                            peg_ratio = VALUES(peg_ratio),
                            pb_ratio = VALUES(pb_ratio),
                            roe = VALUES(roe),
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
                        'ml': rec.get('ml_confidence'),
                        'price': rec['current_price'],
                        's1': rec.get('support_1'),
                        's2': rec.get('support_2'),
                        'r1': rec.get('resistance_1'),
                        'r2': rec.get('resistance_2'),
                        'pe': rec.get('pe_ratio'),
                        'peg': rec.get('peg_ratio'),
                        'pb': rec.get('pb_ratio'),
                        'roe': rec.get('roe'),
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
