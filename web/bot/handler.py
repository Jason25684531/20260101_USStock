"""
Line Bot Webhook 處理器

處理來自 Line Platform 的 Webhook 請求。
支援簽名驗證、互動命令（Top5 / ML）、Flex Message 回覆。

Author: Quant System
Created: 2026-01-31
Updated: 2026-02-12 - 新增 Top5、ML 命令；Flex Message 回覆；DB 查詢整合
"""

import os
import sys
import importlib
import hashlib
import hmac
import base64
import json
import threading
import requests as http_requests
from pathlib import Path
from typing import Optional, List
from datetime import datetime
from flask import Blueprint, request, abort, jsonify
from functools import wraps

from security import get_secret
from db import get_engine, table_exists as _table_exists, column_exists as _column_exists

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_STRATEGIES_SRC = _PROJECT_ROOT / 'strategies' / 'src'
_STRATEGIES_SRC_STR = str(_STRATEGIES_SRC)
if _STRATEGIES_SRC_STR not in sys.path:
    sys.path.insert(0, _STRATEGIES_SRC_STR)

try:
    from utils.line_flex import (
        build_decision_bubble as _build_decision_bubble,
    )  # type: ignore[reportMissingImports]
except ImportError:
    _build_decision_bubble = importlib.import_module('utils.line_flex').build_decision_bubble

# ============================================
# Blueprint & Secrets
# ============================================
line_bot_bp = Blueprint('line_bot', __name__)

CHANNEL_SECRET = get_secret('line_channel_secret', '')
CHANNEL_TOKEN = get_secret('line_channel_token', '')

# Lazy DB Engine
_db_engine = None


def _get_db_engine():
    """延遲初始化 DB 引擎"""
    global _db_engine
    if _db_engine is None:
        _db_engine = get_engine()
    return _db_engine


def _get_daily_screener_class():
    """延遲匯入 DailyScreener，避免 web 啟動時路徑問題。"""
    project_root = Path(__file__).resolve().parents[2]
    strategies_src = project_root / 'strategies' / 'src'

    for path in (project_root, strategies_src):
        path_str = str(path)
        if path_str not in sys.path:
            sys.path.insert(0, path_str)

    screener_engine = importlib.import_module('screener.engine')
    return screener_engine.DailyScreener


# ============================================
# 簽名驗證
# ============================================
def verify_signature(func):
    """驗證 Line Webhook 簽名的裝飾器"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        signature = request.headers.get('X-Line-Signature', '')
        
        # 如果未配置 Channel Secret，允許請求通過（僅供開發環境）
        if not CHANNEL_SECRET:
            print("⚠️  Channel Secret 未配置，跳過簽名驗證（僅限開發環境）")
            return func(*args, **kwargs)
        
        if not signature:
            print("❌ 缺少 X-Line-Signature 標頭")
            abort(400, description="Missing X-Line-Signature header")

        try:
            body = request.get_data(as_text=True)
            hash_value = hmac.new(
                CHANNEL_SECRET.encode('utf-8'),
                body.encode('utf-8'),
                hashlib.sha256,
            ).digest()
            expected = base64.b64encode(hash_value).decode('utf-8')

            if not hmac.compare_digest(signature, expected):
                print("❌ 簽名驗證失敗")
                print(f"   收到: {signature[:20]}...")
                print(f"   預期: {expected[:20]}...")
                abort(403, description="Invalid signature")
            
            print("✅ 簽名驗證成功")
        except Exception as e:
            print(f"❌ 簽名驗證異常: {e}")
            abort(403, description=f"Signature verification error: {str(e)}")

        return func(*args, **kwargs)
    return wrapper


# ============================================
# Webhook 路由
# ============================================
@line_bot_bp.route('/callback', methods=['GET'])
def callback_health():
    """LINE Webhook 健康檢查端點（GET 請求）"""
    return jsonify({
        'status': 'ok',
        'message': 'LINE Bot Webhook is running',
        'endpoint': '/callback',
        'methods': ['GET', 'POST']
    }), 200


@line_bot_bp.route('/callback', methods=['POST'])
@verify_signature
def callback():
    """LINE Webhook 回調端點（POST 請求）- 已啟用簽名驗證"""
    try:
        body = request.get_json()
        if not body:
            print("⚠️  收到空的請求 body")
            return jsonify({'status': 'error', 'message': 'Empty body'}), 400

        events = body.get('events', [])
        print(f"📨 收到 {len(events)} 個事件")

        for event in events:
            event_type = event.get('type')
            print(f"🔔 處理事件類型: {event_type}")
            
            if event_type == 'message':
                handle_message_event(event)
            elif event_type == 'follow':
                handle_follow_event(event)
            elif event_type == 'unfollow':
                user_id = event.get('source', {}).get('userId', 'unknown')
                print(f"👋 用戶取消關注: {user_id}")
            else:
                print(f"📨 未處理事件: {event_type}")

        return jsonify({'status': 'ok'}), 200

    except Exception as e:
        print(f"❌ Webhook 處理錯誤: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ============================================
# 事件處理
# ============================================
def handle_message_event(event: dict):
    """處理文字消息事件"""
    message = event.get('message', {})
    if message.get('type') != 'text':
        return

    text = message.get('text', '')
    user_id = event.get('source', {}).get('userId', 'unknown')
    reply_token = event.get('replyToken')

    print(f"📩 收到文字消息: '{text}' from {user_id}")

    messages = process_command(text, user_id=user_id)
    if messages and reply_token:
        reply_messages(reply_token, messages)


def handle_follow_event(event: dict):
    """處理新用戶關注事件"""
    user_id = event.get('source', {}).get('userId', 'unknown')
    reply_token = event.get('replyToken')
    print(f"👋 新用戶關注: {user_id}")

    welcome = (
        "🎉 歡迎使用美股量化交易系統！\n\n"
        "可用命令：\n"
        "🏆 Top5 — 選股推薦（含 ML 加權）\n"
        "📊 Top5基礎 — 純規則推薦\n"
        "🔍 /stock AAPL — 個股分析\n"
        "🌍 /market — 宏觀環境\n"
        "📅 /history — 歷史推薦\n"
        "🏭 /sector — 產業動能\n"
        "🤖 ML AAPL — ML 預測\n"
        "❓ /help — 完整幫助\n\n"
        "系統每日自動推送選股報告。"
    )

    if reply_token:
        reply_messages(reply_token, [_text_msg(welcome)])


# ============================================
# 命令解析
# ============================================
def process_command(text: str, user_id: Optional[str] = None) -> Optional[List[dict]]:
    """
    處理用戶命令

    Returns:
        LINE message object 列表，或 None (非命令)
    """
    cmd = text.strip().lower()

    # --- Web URL 查詢 ---
    if cmd in ('web', '/web', '網址'):
        return _cmd_web()

    # --- Top5 / scan 命令 ---
    if cmd in ('top5', 'top 5', '推薦', '/top5', '/scan'):
        if user_id and user_id != 'unknown':
            return _cmd_top5_realtime(user_id)
        return _cmd_top5()

    # --- Top5 基礎版（純規則，無 ML）---
    if cmd in ('top5基礎', 'top5-basic', '/top5basic', '/basic', '基礎'):
        return _cmd_top5_basic()

    # --- ML 命令 ---
    if cmd.startswith(('ml ', '/ml ')) or cmd in ('ml', '/ml'):
        parts = text.strip().split()
        if len(parts) >= 2:
            return _cmd_ml(parts[1].upper())
        return [_text_msg("請指定股票代碼，例如: ML AAPL")]

    # --- /stock SYMBOL: 個股 11 策略詳細分析 ---
    if cmd.startswith(('/stock ', '個股 ', '查股 ')):
        parts = text.strip().split()
        if len(parts) >= 2:
            return _cmd_stock(parts[1].upper())
        return [_text_msg("請指定股票代碼，例如: /stock AAPL")]

    # --- /market: 宏觀環境 ---
    if cmd in ('/market', '市場', '宏觀', '/macro'):
        return _cmd_market()

    # --- /history MMDD: 歷史推薦 ---
    if cmd.startswith(('/history', '歷史')):
        parts = text.strip().split()
        date_str = parts[1] if len(parts) >= 2 else None
        return _cmd_history(date_str)

    # --- /sector: 產業動能 ---
    if cmd in ('/sector', '產業', '板塊', '/sectors'):
        return _cmd_sector()

    # --- Status (real health check) ---
    if cmd in ('/status', '狀態'):
        return _cmd_status()

    # --- Help ---
    if cmd in ('/help', '幫助'):
        return [_text_msg(
            "📚 可用命令：\n\n"
            "🏆 Top5 — 今日選股推薦（含 ML）\n"
            "📊 Top5基礎 — 純規則推薦\n"
            "🔍 /stock AAPL — 個股詳細分析\n"
            "🌍 /market — 宏觀環境\n"
            "📅 /history 0214 — 歷史推薦\n"
            "🏭 /sector — 產業動能排行\n"
            "🤖 ML AAPL — ML 預測\n"
            "📈 /status — 即時系統狀態\n"
            "🎯 /strategies — 策略說明\n"
            "❓ /help — 顯示此幫助\n\n"
            "💡 點擊 Top5 推薦下方按鈕快速查股"
        )]

    # --- Strategies ---
    if cmd in ('/strategies', '策略'):
        return [_text_msg(
            "📈 選股策略 v2（11 策略 + ML）：\n\n"
            "📋 規則策略（11 項）:\n"
            "  1️⃣ Breakout — 200日新高突破\n"
            "  2️⃣ Acceleration — 均速曲率加速\n"
            "  3️⃣ PEG — PEG<1.5 + ROE>10%\n"
            "  4️⃣ DuPont — 杜邦分解品質\n"
            "  5️⃣ Institutional — 機構籌碼\n"
            "  6️⃣ Volume Structure — 量價結構\n"
            "  7️⃣ Money Flow — 資金流向\n"
            "  8️⃣ Multi-TF Momentum — 多週期動能\n"
            "  9️⃣ Relative Strength — 相對強度\n"
            "  🔟 Earnings Quality — 盈餘品質\n"
            "  1️⃣1️⃣ Sector Rotation — 產業輪動\n\n"
            "🤖 ML (XGBoost) — 信心度加權\n"
            "📊 評分 = 規則通過數 × ML加權"
        )]

    # 非命令消息
    return None


def _cmd_web() -> List[dict]:
    """回傳目前 Web 戰情室對外網址。"""
    url = (os.getenv('NGROK_URL') or '').strip()
    if not url:
        return [_text_msg("🌐 目前尚未設定 Web 戰情室網址，請先設定 NGROK_URL。")]

    return [_text_msg(
        f"🌐 目前的 Web 戰情室網址是：\n{url}\n\n預設帳號：admin / 密碼：admin123"
    )]


def _cmd_top5_realtime(user_id: str) -> List[dict]:
    """立即回覆受理訊息，背景執行最新 Top5 掃描並主動推播。"""
    worker = threading.Thread(
        target=_run_screener_and_push,
        args=(user_id,),
        daemon=True,
    )
    worker.start()
    return [_text_msg(
        "⏳ 正在為您啟動最新的全市場掃描與 AI 運算，大約需要 1-2 分鐘，請稍候..."
    )]


# ============================================
# /stock SYMBOL: 個股 11 策略分析
# ============================================
def _cmd_stock(symbol: str) -> List[dict]:
    """查詢個股的 11 策略通過/不通過 + 基本面 + ML"""
    try:
        from sqlalchemy import text as sql_text
        engine = _get_db_engine()

        with engine.connect() as conn:
            row = conn.execute(sql_text("""
                SELECT symbol, scan_date, signal_type, total_score,
                       current_price, ml_confidence,
                       breakout_pass, acceleration_pass, peg_pass, dupont_pass,
                       institutional_pass, volume_structure_pass, money_flow_pass,
                       multi_tf_momentum_pass, relative_strength_pass,
                       earnings_quality_pass, sector_rotation_pass,
                       total_strategies, support_1, resistance_1, macro_regime
                FROM daily_recommendations
                WHERE symbol = :sym
                ORDER BY scan_date DESC LIMIT 1
            """), {'sym': symbol}).first()

            if not row:
                return [_text_msg(f"❌ 找不到 {symbol} 的推薦資料")]

            strat_names = [
                ('突破', row[6]), ('加速', row[7]), ('PEG', row[8]), ('杜邦', row[9]),
                ('籌碼', row[10]), ('量價', row[11]), ('資金流', row[12]),
                ('多TF', row[13]), ('RS', row[14]), ('盈餘', row[15]), ('產業', row[16]),
            ]
            passed = [name for name, v in strat_names if v]
            failed = [name for name, v in strat_names if not v]
            total = row[17] or len(strat_names)
            ml_conf = float(row[5]) if row[5] else 0
            ml_str = f"{ml_conf:.0%}" if ml_conf > 0 else "—"
            s1 = f"${float(row[18]):.2f}" if row[18] else "N/A"
            r1 = f"${float(row[19]):.2f}" if row[19] else "N/A"
            regime = row[20] or "N/A"

            msg = (
                f"🔍 {row[0]} 詳細分析\n"
                f"📅 {row[1]} | {row[2]} | 評分 {float(row[3]):.1f}\n"
                f"💰 ${float(row[4]):.2f} | 支撐 {s1} | 壓力 {r1}\n"
                f"🌍 Regime: {regime}\n\n"
                f"✅ 通過 ({len(passed)}/{total}):\n"
                f"  {' | '.join(passed) if passed else '無'}\n\n"
                f"❌ 未通過:\n"
                f"  {' | '.join(failed) if failed else '全通過 🎉'}\n\n"
                f"🤖 ML 信心度: {ml_str}"
            )

            # 查基本面
            fund_row = conn.execute(sql_text("""
                SELECT pe_ratio, peg_ratio, pb_ratio, roe, profit_margin, sector
                FROM stock_fundamentals
                WHERE symbol = :sym
                ORDER BY updated_at DESC LIMIT 1
            """), {'sym': symbol}).first()

            if fund_row:
                pe = f"{float(fund_row[0]):.1f}" if fund_row[0] else "-"
                peg = f"{float(fund_row[1]):.2f}" if fund_row[1] else "-"
                pb = f"{float(fund_row[2]):.1f}" if fund_row[2] else "-"
                roe = f"{float(fund_row[3])*100:.1f}%" if fund_row[3] else "-"
                margin = f"{float(fund_row[4])*100:.1f}%" if fund_row[4] else "-"
                sector = fund_row[5] or "-"
                msg += (
                    f"\n\n📈 基本面:\n"
                    f"  PE {pe} | PEG {peg} | PB {pb}\n"
                    f"  ROE {roe} | 淨利率 {margin}\n"
                    f"  產業: {sector}"
                )

            return [_text_msg(msg)]

    except Exception as e:
        print(f"❌ /stock 查詢失敗: {e}")
        return [_text_msg(f"❌ 查詢 {symbol} 失敗: {e}")]


# ============================================
# /market: 宏觀環境
# ============================================
def _cmd_market() -> List[dict]:
    """查詢宏觀環境 (Regime + FRED 指標)"""
    try:
        from sqlalchemy import text as sql_text
        engine = _get_db_engine()

        with engine.connect() as conn:
            # Regime
            reg = None
            if _table_exists(conn, 'macro_regime_log'):
                reg = conn.execute(sql_text("""
                    SELECT regime, description, report_date
                    FROM macro_regime_log
                    ORDER BY report_date DESC LIMIT 1
                """)).first()

            regime_str = "UNKNOWN"
            regime_emoji = "⚪"
            regime_desc = ""
            regime_date = ""
            if reg:
                regime_str = reg[0] or "UNKNOWN"
                regime_desc = reg[1] or ""
                regime_date = str(reg[2]) if reg[2] else ""
                regime_emoji = {"RISK_ON": "🟢", "NEUTRAL": "🟡", "RISK_OFF": "🔴"}.get(regime_str, "⚪")

            # FRED indicators
            indicators = {}
            if _table_exists(conn, 'macro_data'):
                if _column_exists(conn, 'macro_data', 'indicator'):
                    code_col = 'indicator'
                elif _column_exists(conn, 'macro_data', 'ticker'):
                    code_col = 'ticker'
                else:
                    code_col = None

                code_alias_map = {
                    'VIX': ['VIX', 'VIXCLS'],
                    'T10Y2Y': ['T10Y2Y'],
                    'UNRATE': ['UNRATE'],
                    'DFF': ['DFF'],
                    'CPIAUCSL': ['CPIAUCSL', 'CPI'],
                }

                if code_col:
                    for indicator in ['VIX', 'T10Y2Y', 'UNRATE', 'DFF', 'CPIAUCSL']:
                        r = None
                        for alias in code_alias_map.get(indicator, [indicator]):
                            r = conn.execute(sql_text(f"""
                                SELECT value FROM macro_data
                                WHERE {code_col} = :ind
                                ORDER BY date DESC LIMIT 1
                            """), {'ind': alias}).first()
                            if r:
                                break
                        if r:
                            indicators[indicator] = float(r[0])

            vix = indicators.get('VIX')
            vix_str = f"{vix:.1f}" if vix else "-"
            vix_emoji = "🟢" if vix and vix < 20 else "🟡" if vix and vix < 30 else "🔴"

            yield_curve = indicators.get('T10Y2Y')
            yc_str = f"{yield_curve:.2f}" if yield_curve is not None else "-"

            unrate = indicators.get('UNRATE')
            ur_str = f"{unrate:.1f}%" if unrate else "-"

            fed = indicators.get('DFF')
            fed_str = f"{fed:.2f}%" if fed else "-"

            if regime_str == "UNKNOWN" and indicators:
                if yield_curve is not None and yield_curve < 0:
                    regime_str = "RISK_OFF"
                    regime_emoji = "🔴"
                    regime_desc = "Fallback: 殖利率倒掛，偏防禦"
                elif yield_curve is not None and yield_curve > 0.3 and (fed is None or fed < 5.0):
                    regime_str = "RISK_ON"
                    regime_emoji = "🟢"
                    regime_desc = "Fallback: 曲線正向且利率中性，偏風險資產"
                else:
                    regime_str = "NEUTRAL"
                    regime_emoji = "🟡"
                    regime_desc = "Fallback: 宏觀信號中性"

            msg = (
                f"🌍 宏觀環境報告\n"
                f"{'='*24}\n\n"
                f"{regime_emoji} Regime: {regime_str}\n"
                f"  {regime_desc}\n"
                f"  📅 {regime_date}\n\n"
                f"📊 關鍵指標:\n"
                f"  {vix_emoji} VIX: {vix_str}\n"
                f"  📈 殖利率曲線: {yc_str}\n"
                f"  👷 失業率: {ur_str}\n"
                f"  🏦 Fed 利率: {fed_str}\n\n"
                f"💡 Regime 影響選股加權:\n"
                f"  🟢 RISK_ON = 積極進場\n"
                f"  🟡 NEUTRAL = 正常配置\n"
                f"  🔴 RISK_OFF = 保守防禦"
            )
            return [_text_msg(msg)]

    except Exception as e:
        print(f"❌ /market 查詢失敗: {e}")
        return [_text_msg(f"❌ 宏觀資料查詢失敗: {e}")]


# ============================================
# /history MMDD: 歷史推薦
# ============================================
def _cmd_history(date_str: Optional[str] = None) -> List[dict]:
    """查詢歷史推薦日期列表或指定日期的推薦"""
    try:
        from sqlalchemy import text as sql_text
        engine = _get_db_engine()

        with engine.connect() as conn:
            if date_str:
                # Parse MMDD or YYYYMMDD
                now = datetime.now()
                if len(date_str) == 4:
                    target = f"{now.year}-{date_str[:2]}-{date_str[2:]}"
                elif len(date_str) == 8:
                    target = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
                else:
                    target = date_str  # assume YYYY-MM-DD

                rows = conn.execute(sql_text("""
                    SELECT symbol, rank_position, signal_type, total_score, ml_confidence
                    FROM daily_recommendations
                    WHERE scan_date = :d
                    ORDER BY rank_position ASC LIMIT 10
                """), {'d': target})

                recs = [r for r in rows]
                if not recs:
                    return [_text_msg(f"📅 {target} 無推薦資料")]

                lines = [f"📅 {target} 推薦:", ""]
                for r in recs:
                    ml = f"{float(r[4])*100:.0f}%" if r[4] else "—"
                    lines.append(f"  #{r[1]} {r[0]} | {r[2]} | 分:{float(r[3]):.1f} | ML:{ml}")

                return [_text_msg("\n".join(lines))]
            else:
                # List recent dates
                dates = conn.execute(sql_text("""
                    SELECT DISTINCT scan_date FROM daily_recommendations
                    ORDER BY scan_date DESC LIMIT 10
                """))
                date_list = [str(r[0]) for r in dates]

                if not date_list:
                    return [_text_msg("📅 尚無歷史推薦資料")]

                msg = "📅 歷史推薦日期:\n\n"
                for d in date_list:
                    msg += f"  • {d}\n"
                msg += "\n💡 輸入 /history 0214 查看特定日期"
                return [_text_msg(msg)]

    except Exception as e:
        print(f"❌ /history 查詢失敗: {e}")
        return [_text_msg(f"❌ 歷史推薦查詢失敗: {e}")]


# ============================================
# /sector: 產業動能排行
# ============================================
def _cmd_sector() -> List[dict]:
    """查詢產業動能排行"""
    try:
        from sqlalchemy import text as sql_text
        engine = _get_db_engine()

        with engine.connect() as conn:
            sectors = []

            if _table_exists(conn, 'sector_momentum'):
                etf_col = 'etf' if _column_exists(conn, 'sector_momentum', 'etf') else 'etf_symbol'
                rows = conn.execute(sql_text(f"""
                    SELECT sector, {etf_col}, rank_position, return_20d, return_63d
                    FROM sector_momentum
                    WHERE report_date = (SELECT MAX(report_date) FROM sector_momentum)
                    ORDER BY rank_position ASC
                """))
                sectors = [r for r in rows]

            # fallback: 若無 sector_momentum，用 daily_recommendations 聚合
            if not sectors and _table_exists(conn, 'daily_recommendations'):
                if _column_exists(conn, 'daily_recommendations', 'sector'):
                    rows = conn.execute(sql_text("""
                        SELECT COALESCE(sector, 'Unknown') AS sector_name,
                               COUNT(*) AS stock_count,
                               AVG(total_score) AS avg_score
                        FROM daily_recommendations
                        WHERE scan_date = (SELECT MAX(scan_date) FROM daily_recommendations)
                        GROUP BY COALESCE(sector, 'Unknown')
                        ORDER BY avg_score DESC, stock_count DESC
                    """))
                    rank = 1
                    for row in rows:
                        sectors.append((row[0], 'N/A', rank, None, None))
                        rank += 1
                else:
                    rows = conn.execute(sql_text("""
                        SELECT symbol, total_score
                        FROM daily_recommendations
                        WHERE scan_date = (SELECT MAX(scan_date) FROM daily_recommendations)
                    """))
                    from constants import SECTOR_MAP_FALLBACK
                    sector_map = SECTOR_MAP_FALLBACK
                    agg = {}
                    for row in rows:
                        sector_name = sector_map.get(row[0], 'Other')
                        agg[sector_name] = agg.get(sector_name, 0) + 1
                    sorted_items = sorted(agg.items(), key=lambda item: item[1], reverse=True)
                    rank = 1
                    for sector_name, _count in sorted_items:
                        sectors.append((sector_name, 'N/A', rank, None, None))
                        rank += 1

            if not sectors:
                return [_text_msg("🏭 尚無產業動能資料")]

            lines = ["🏭 產業動能排行", "=" * 24, ""]
            for s in sectors:
                r20 = f"{float(s[3])*100:.1f}%" if s[3] else "-"
                r63 = f"{float(s[4])*100:.1f}%" if s[4] else "-"
                arrow = "📈" if s[3] and float(s[3]) > 0 else "📉"
                lines.append(f"  #{s[2]} {arrow} {s[0]} ({s[1]})")
                lines.append(f"     20日: {r20} | 63日: {r63}")

            lines.append("\n💡 輸入 /stock SYMBOL 查看個股")
            return [_text_msg("\n".join(lines))]

    except Exception as e:
        print(f"❌ /sector 查詢失敗: {e}")
        return [_text_msg(f"❌ 產業動能查詢失敗: {e}")]


# ============================================
# /status: 即時系統健康檢查
# ============================================
def _cmd_status() -> List[dict]:
    """即時健康檢查，回報 DB、API、ML"""
    try:
        from sqlalchemy import text as sql_text
        engine = _get_db_engine()

        db_ok = False
        latest_rec = "N/A"
        rec_count = 0
        try:
            with engine.connect() as conn:
                conn.execute(sql_text("SELECT 1"))
                db_ok = True
                r = conn.execute(sql_text(
                    "SELECT MAX(scan_date), COUNT(*) FROM daily_recommendations"
                )).first()
                if r:
                    latest_rec = str(r[0]) if r[0] else "N/A"
                    rec_count = r[1] or 0
        except Exception:
            pass

        db_emoji = "🟢" if db_ok else "🔴"
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        msg = (
            f"📊 系統狀態報告\n"
            f"{'='*24}\n\n"
            f"{db_emoji} 資料庫: {'已連接' if db_ok else '斷線'}\n"
            f"📈 最新推薦: {latest_rec}\n"
            f"📋 總推薦數: {rec_count:,}\n"
            f"🤖 策略引擎: v2 (11策略+ML)\n"
            f"⏰ 查詢時間: {now}"
        )
        return [_text_msg(msg)]

    except Exception as e:
        return [_text_msg(f"❌ 狀態查詢失敗: {e}")]


# ============================================
# Top5 命令：查詢最新選股推薦
# ============================================
def _cmd_top5() -> List[dict]:
    """查詢 DB 最新 Top 5 推薦，回傳 Flex Carousel"""
    try:
        from sqlalchemy import text as sql_text
        engine = _get_db_engine()

        with engine.connect() as conn:
            latest = conn.execute(sql_text(
                "SELECT MAX(scan_date) FROM daily_recommendations"
            )).scalar()

            if not latest:
                return [_text_msg(
                    "📊 尚無選股推薦資料\n\n"
                    "請先執行:\n"
                    "python strategies/scripts/run_daily_screener.py --save-db"
                )]

            rows = conn.execute(sql_text("""
                SELECT symbol, rank_position, signal_type, total_score,
                       current_price, target_price, ml_confidence,
                       institutional_ownership, insider_sentiment,
                       valuation_status, buy_price, sell_price, reason_summary,
                       support_1, resistance_1,
                       breakout_pass, acceleration_pass, peg_pass, dupont_pass
                FROM daily_recommendations
                WHERE scan_date = :d
                ORDER BY rank_position ASC
                LIMIT 5
            """), {'d': str(latest)}).mappings()

            recs = []
            for row in rows:
                recs.append({
                    'symbol': row['symbol'],
                    'rank': row['rank_position'],
                    'signal': row['signal_type'],
                    'total_score': float(row['total_score']) if row['total_score'] else 0,
                    'current_price': float(row['current_price']) if row['current_price'] else 0,
                    'target_price': float(row['target_price']) if row['target_price'] is not None else None,
                    'ml_confidence': float(row['ml_confidence']) if row['ml_confidence'] else 0,
                    'institutional_ownership': float(row['institutional_ownership']) if row['institutional_ownership'] is not None else None,
                    'insider_sentiment': row['insider_sentiment'] or 'NEUTRAL',
                    'valuation_status': row['valuation_status'] or 'FAIR',
                    'buy_price': float(row['buy_price']) if row['buy_price'] is not None else None,
                    'sell_price': float(row['sell_price']) if row['sell_price'] is not None else None,
                    'reason_summary': row['reason_summary'] or '綜合訊號中性，待更多確認',
                    'support_1': float(row['support_1']) if row['support_1'] else None,
                    'resistance_1': float(row['resistance_1']) if row['resistance_1'] else None,
                    'breakout_pass': bool(row['breakout_pass']),
                    'acceleration_pass': bool(row['acceleration_pass']),
                    'peg_pass': bool(row['peg_pass']),
                    'dupont_pass': bool(row['dupont_pass']),
                })

            if not recs:
                return [_text_msg("📊 該日期無推薦資料")]

            # Build Flex message + Quick Reply for individual stock lookup
            flex = _build_top5_flex(recs, str(latest))
            quick_items = [
                {"type": "action", "action": {"type": "message", "label": f"🔍{r['symbol']}", "text": f"/stock {r['symbol']}"}}
                for r in recs[:5]
            ]
            quick_items.append({"type": "action", "action": {"type": "message", "label": "🌍 宏觀", "text": "/market"}})
            flex["quickReply"] = {"items": quick_items}
            return [flex]

    except Exception as e:
        print(f"❌ Top5 查詢失敗: {e}")
        return [_text_msg(f"❌ 查詢失敗: {e}")]


# ============================================
# Top5 基礎版命令：純規則推薦（無 ML 加權）
# ============================================
def _cmd_top5_basic() -> List[dict]:
    """查詢 DB 最新 Top 5 推薦（純規則版，顯示原始規則評分）"""
    try:
        from sqlalchemy import text as sql_text
        engine = _get_db_engine()

        with engine.connect() as conn:
            # 查詢與 _cmd_top5() 相同的資料，但呈現時顯示純規則邏輯
            latest = conn.execute(sql_text(
                "SELECT MAX(scan_date) FROM daily_recommendations"
            )).scalar()

            if not latest:
                return [_text_msg(
                    "📊 尚無選股推薦資料\n\n"
                    "請先執行:\n"
                    "python strategies/scripts/run_daily_screener.py --save-db"
                )]

            rows = conn.execute(sql_text("""
                SELECT symbol, rank_position, signal_type, total_score,
                       current_price, target_price, ml_confidence,
                       institutional_ownership, insider_sentiment,
                       valuation_status, buy_price, sell_price, reason_summary,
                       support_1, resistance_1,
                       breakout_pass, acceleration_pass, peg_pass, dupont_pass
                FROM daily_recommendations
                WHERE scan_date = :d
                ORDER BY rank_position ASC
                LIMIT 5
            """), {'d': str(latest)}).mappings()

            recs = []
            for row in rows:
                # 計算純規則評分（不考慮 ML 加權）
                ml_conf = float(row['ml_confidence']) if row['ml_confidence'] else 0
                total_score = float(row['total_score']) if row['total_score'] else 0
                
                # 反推原始規則分：如果有 ML 加權，除回去
                if ml_conf > 0:
                    rule_score = total_score / (ml_conf / 0.5)
                else:
                    rule_score = total_score
                
                recs.append({
                    'symbol': row['symbol'],
                    'rank': row['rank_position'],
                    'signal': row['signal_type'],
                    'total_score': round(rule_score, 2),  # 使用純規則分
                    'current_price': float(row['current_price']) if row['current_price'] else 0,
                    'target_price': float(row['target_price']) if row['target_price'] is not None else None,
                    'ml_confidence': 0,  # 強制顯示 0（無 ML）
                    'institutional_ownership': float(row['institutional_ownership']) if row['institutional_ownership'] is not None else None,
                    'insider_sentiment': row['insider_sentiment'] or 'NEUTRAL',
                    'valuation_status': row['valuation_status'] or 'FAIR',
                    'buy_price': float(row['buy_price']) if row['buy_price'] is not None else None,
                    'sell_price': float(row['sell_price']) if row['sell_price'] is not None else None,
                    'reason_summary': row['reason_summary'] or '綜合訊號中性，待更多確認',
                    'support_1': float(row['support_1']) if row['support_1'] else None,
                    'resistance_1': float(row['resistance_1']) if row['resistance_1'] else None,
                    'breakout_pass': bool(row['breakout_pass']),
                    'acceleration_pass': bool(row['acceleration_pass']),
                    'peg_pass': bool(row['peg_pass']),
                    'dupont_pass': bool(row['dupont_pass']),
                })

            if not recs:
                return [_text_msg("📊 該日期無推薦資料")]

            # 使用相同 Flex 格式，但評分已改為純規則分（ML 顯示為 —）
            return [_build_top5_flex(recs, f"{str(latest)} (純規則)")]

    except Exception as e:
        print(f"❌ Top5 基礎版查詢失敗: {e}")
        return [_text_msg(f"❌ 查詢失敗: {e}")]


# ============================================
# ML 命令：查詢單支股票 ML 預測
# ============================================
def _cmd_ml(symbol: str) -> List[dict]:
    """查詢 DB 中指定股票的最新 ML 預測"""
    try:
        from sqlalchemy import text as sql_text
        engine = _get_db_engine()

        with engine.connect() as conn:
            # 優先查 trade_logs（含 confidence + top_features）
            row = None
            if _table_exists(conn, 'trade_logs') and _column_exists(conn, 'trade_logs', 'confidence'):
                top_col = 'top_features' if _column_exists(conn, 'trade_logs', 'top_features') else 'NULL AS top_features'
                row = conn.execute(sql_text(f"""
                    SELECT symbol, entry_date, entry_price, confidence, {top_col}
                    FROM trade_logs
                    WHERE symbol = :sym AND confidence IS NOT NULL
                    ORDER BY entry_date DESC, id DESC
                    LIMIT 1
                """), {'sym': symbol}).first()

            if row:
                conf = float(row[3]) if row[3] else 0
                conf_str = f"{conf:.0%}" if conf > 0 else "—"
                features = json.loads(row[4]) if row[4] else None

                msg = (
                    f"🤖 {row[0]} ML 預測\n\n"
                    f"📅 日期: {row[1]}\n"
                    f"💰 價格: ${float(row[2]):.2f}\n"
                    f"🎯 信心度: {conf_str}"
                )
                if features:
                    msg += "\n\n📋 重要特徵:"
                    for f in features[:5]:
                        if isinstance(f, dict):
                            msg += f"\n  • {f.get('feature', 'N/A')}: {f.get('importance', 0):.4f}"
                        else:
                            msg += f"\n  • {f}"

                return [_text_msg(msg)]

            # 備選：查 daily_recommendations
            row2 = conn.execute(sql_text("""
                SELECT symbol, scan_date, current_price, ml_confidence,
                       total_score, signal_type, support_1, resistance_1
                FROM daily_recommendations
                WHERE symbol = :sym
                ORDER BY scan_date DESC
                LIMIT 1
            """), {'sym': symbol}).first()

            if not row2:
                return [_text_msg(f"❌ 找不到 {symbol} 的 ML 預測資料")]

            conf = float(row2[3]) if row2[3] else 0
            conf_str = f"{conf:.0%}" if conf > 0 else "—"
            s1 = f"${float(row2[6]):.2f}" if row2[6] else "N/A"
            r1 = f"${float(row2[7]):.2f}" if row2[7] else "N/A"

            return [_text_msg(
                f"🤖 {row2[0]} ML 預測\n\n"
                f"📅 日期: {row2[1]}\n"
                f"💰 價格: ${float(row2[2]):.2f}\n"
                f"📊 評分: {float(row2[4]):.1f}/5\n"
                f"🎯 信號: {row2[5]}\n"
                f"🤖 ML 信心度: {conf_str}\n"
                f"📉 支撐: {s1}\n"
                f"📈 壓力: {r1}"
            )]

    except Exception as e:
        print(f"❌ ML 查詢失敗: {e}")
        return [_text_msg(f"❌ 查詢 {symbol} 失敗: {e}")]


# ============================================
# Flex Message 建構
# ============================================
def _build_top5_flex(recs: list, scan_date: str) -> dict:
    """建構 Top 5 推薦的 Flex Carousel"""
    bubbles = [_build_bubble(rec) for rec in recs]
    return {
        "type": "flex",
        "altText": f"📊 每日選股推薦 Top {len(recs)} — {scan_date}",
        "contents": {
            "type": "carousel",
            "contents": bubbles,
        },
    }


def _build_bubble(rec: dict) -> dict:
    """建構單支股票的三層決策 Flex Bubble。"""
    return _build_decision_bubble(rec)


# ============================================
# LINE Reply 共用
# ============================================
def _text_msg(s: str) -> dict:
    """建構 LINE Text Message 物件"""
    return {"type": "text", "text": s.strip()}


def reply_messages(reply_token: str, messages: List[dict]):
    """
    回覆消息（支援 text + flex）

    Args:
        reply_token: Line 回覆令牌
        messages: LINE message object 列表
    """
    if not CHANNEL_TOKEN:
        print("⚠️  Channel Token 未配置，無法回覆消息")
        return

    try:
        resp = http_requests.post(
            "https://api.line.me/v2/bot/message/reply",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {CHANNEL_TOKEN}",
            },
            json={
                "replyToken": reply_token,
                "messages": messages[:5],  # LINE 每次回覆最多 5 則
            },
            timeout=10,
        )
        if resp.status_code == 200:
            print("✅ 消息回覆成功")
        else:
            print(f"❌ 消息回覆失敗: {resp.status_code} - {resp.text}")
    except Exception as e:
        print(f"❌ 回覆請求失敗: {e}")


def push_message(user_id: str, messages: List[dict]) -> bool:
    """主動推播消息給指定 LINE 使用者。"""
    if not CHANNEL_TOKEN:
        print("⚠️  Channel Token 未配置，無法主動推播")
        return False

    try:
        resp = http_requests.post(
            "https://api.line.me/v2/bot/message/push",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {CHANNEL_TOKEN}",
            },
            json={
                "to": user_id,
                "messages": messages[:5],
            },
            timeout=15,
        )
        if resp.status_code == 200:
            print(f"✅ Push 成功: {user_id}")
            return True

        print(f"❌ Push 失敗: {resp.status_code} - {resp.text}")
    except Exception as e:
        print(f"❌ Push 請求失敗: {e}")

    return False


def _run_screener_and_push(user_id: str):
    """背景執行最新全市場掃描，完成後主動推播 Top5。"""
    try:
        DailyScreener = _get_daily_screener_class()
        screener = DailyScreener(use_ml=True)
        df_all = screener.scan_all()
        recommendations = screener.get_top_recommendations(df_all, n=5)

        if not recommendations:
            push_message(user_id, [_text_msg("📊 最新掃描未產生可用推薦結果。")])
            return

        screener.save_to_db(recommendations)
        flex = _build_top5_flex(recommendations, datetime.now().strftime('%Y-%m-%d'))
        push_message(user_id, [flex])
    except Exception as e:
        print(f"❌ 背景 Top5 掃描失敗: {type(e).__name__}: {e}")
        push_message(user_id, [_text_msg(f"❌ 最新掃描失敗: {e}")])


# ============================================
# Debug 路由
# ============================================
@line_bot_bp.route('/webhook/info', methods=['GET'])
def webhook_info():
    """返回 Webhook 配置信息（用於調試）"""
    return jsonify({
        'status': 'active',
        'endpoint': '/callback',
        'channel_secret_configured': bool(CHANNEL_SECRET),
        'channel_token_configured': bool(CHANNEL_TOKEN),
    })
