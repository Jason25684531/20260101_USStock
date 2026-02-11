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
import os
import sys
import json
import time
from pathlib import Path
from datetime import datetime, date
from typing import List, Dict, Optional, Tuple

import pandas as pd
import numpy as np
import yfinance as yf

# 路徑設定
_SRC_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(_SRC_DIR))

from strategies.momentum import screen_breakout, screen_acceleration
from strategies.fundamental import screen_peg, screen_dupont
from screener.support_resistance import calc_support_resistance
from config import DEFAULT_SYMBOLS, calc_rule_score


class DailyScreener:
    """每日選股引擎"""

    def __init__(
        self,
        symbols: List[str] = None,
        use_ml: bool = False,
        top_n: int = 5,
        delay: float = 0.3,
    ):
        """
        Args:
            symbols: 股票池 (預設 DEFAULT_SYMBOLS)
            use_ml: 是否啟用 ML 信心度加權
            top_n: 輸出 Top N 推薦
            delay: yfinance 請求間隔秒數, 避免限流
        """
        self.symbols = symbols or DEFAULT_SYMBOLS
        self.use_ml = use_ml
        self.top_n = top_n
        self.delay = delay
        self._ml_strategy = None

        if self.use_ml:
            self._init_ml()

    def _init_ml(self):
        """嘗試載入 ML 策略 (若 model.pkl 不存在則降級)"""
        try:
            from strategies.ml_strategy import MLStrategy
            self._ml_strategy = MLStrategy()
            print("✅ ML 策略已載入, 將作為第 5 評分維度")
        except Exception as e:
            print(f"⚠️  ML 策略載入失敗, 僅使用規則策略: {e}")
            self._ml_strategy = None

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

        close_col = 'Close' if 'Close' in df.columns else 'close'
        current_price = float(df[close_col].iloc[-1])

        # --- 4 個規則策略 ---
        r_breakout = screen_breakout(df)
        r_accel = screen_acceleration(df, n=20)
        r_peg = screen_peg(info)
        r_dupont = screen_dupont(info)

        # --- ML 信心度 (可選) ---
        ml_conf = 0.0
        ml_signal = 'N/A'
        if self._ml_strategy:
            try:
                signal, prob, _ = self._ml_strategy.generate_signal(symbol)
                ml_conf = float(prob) if signal == 'BUY' else 0.0
                ml_signal = signal
            except Exception:
                pass

        # --- 綜合評分 ---
        rule_score = calc_rule_score(r_breakout, r_accel, r_peg, r_dupont)
        total_score = rule_score + ml_conf  # 0 ~ 5

        # --- 支撐壓力 ---
        sr = calc_support_resistance(df)

        # --- 信號判定 ---
        # BUY: 至少 2 個策略通過 或 總分 >= 2.0
        passes = sum([r_breakout['pass'], r_accel['pass'], r_peg['pass'], r_dupont['pass']])
        signal_type = 'BUY' if passes >= 2 or total_score >= 2.0 else 'SELL'

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
