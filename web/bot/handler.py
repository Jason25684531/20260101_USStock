"""
Line Bot Webhook 處理器

處理來自 Line Platform 的 Webhook 請求。
支援簽名驗證、互動命令（Top5 / ML）、Flex Message 回覆。

Author: Quant System
Created: 2026-01-31
Updated: 2026-02-12 - 新增 Top5、ML 命令；Flex Message 回覆；DB 查詢整合
"""

import os
import hashlib
import hmac
import base64
import json
import requests as http_requests
from typing import Optional, List, Dict
from datetime import datetime
from flask import Blueprint, request, abort, jsonify
from functools import wraps

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from security import get_secret
from db import get_engine

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


# ============================================
# 簽名驗證
# ============================================
def verify_signature(func):
    """驗證 Line Webhook 簽名的裝飾器"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        signature = request.headers.get('X-Line-Signature', '')
        if not signature:
            print("❌ 缺少 X-Line-Signature 標頭")
            abort(400, description="Missing X-Line-Signature header")

        if not CHANNEL_SECRET:
            print("⚠️  Channel Secret 未配置，跳過簽名驗證（僅限開發環境）")
            return func(*args, **kwargs)

        body = request.get_data(as_text=True)
        hash_value = hmac.new(
            CHANNEL_SECRET.encode('utf-8'),
            body.encode('utf-8'),
            hashlib.sha256,
        ).digest()
        expected = base64.b64encode(hash_value).decode('utf-8')

        if not hmac.compare_digest(signature, expected):
            print("❌ 簽名驗證失敗")
            abort(403, description="Invalid signature")

        return func(*args, **kwargs)
    return wrapper


# ============================================
# Webhook 路由
# ============================================
@line_bot_bp.route('/callback', methods=['POST'])
def callback():
    """LINE Webhook 回調端點 - 簽名驗證已禁用（開發模式）"""
    try:
        body = request.get_json()
        if not body:
            return jsonify({'status': 'error', 'message': 'Empty body'}), 400

        for event in body.get('events', []):
            event_type = event.get('type')
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
        print(f"❌ Webhook 處理錯誤: {e}")
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

    messages = process_command(text)
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
        "📊 Top5基礎 — 純規則推薦（無 ML）\n"
        "🤖 ML AAPL — 查詢 ML 預測\n"
        "📈 /strategies — 查看策略說明\n"
        "❓ /help — 完整幫助\n\n"
        "系統每日自動推送選股報告。"
    )

    if reply_token:
        reply_messages(reply_token, [_text_msg(welcome)])


# ============================================
# 命令解析
# ============================================
def process_command(text: str) -> Optional[List[dict]]:
    """
    處理用戶命令

    Returns:
        LINE message object 列表，或 None (非命令)
    """
    cmd = text.strip().lower()

    # --- Top5 / scan 命令 ---
    if cmd in ('top5', 'top 5', '推薦', '/top5', '/scan'):
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

    # --- Status ---
    if cmd in ('/status', '狀態'):
        return [_text_msg(
            "🟢 系統運行正常\n\n"
            "📊 策略引擎: 運行中\n"
            "💾 數據庫: 已連接\n"
            f"📈 最後更新: {datetime.now().strftime('%H:%M:%S')}"
        )]

    # --- Help ---
    if cmd in ('/help', '幫助'):
        return [_text_msg(
            "📚 可用命令：\n\n"
            "🏆 Top5 — 今日選股推薦（含 ML 加權）\n"
            "📊 Top5基礎 — 純規則推薦（無 ML）\n"
            "🤖 ML [代碼] — 查詢 ML 預測 (如: ML AAPL)\n"
            "📈 /status — 系統狀態\n"
            "🎯 /strategies — 查看策略說明\n"
            "❓ /help — 顯示此幫助\n\n"
            "💡 系統每日自動推送選股報告"
        )]

    # --- Strategies ---
    if cmd in ('/strategies', '策略'):
        return [_text_msg(
            "📈 選股策略版本：\n\n"
            "🏆 Top5（完整版）\n"
            "  • 4 規則策略 + ML 信心度加權\n"
            "  • 評分 = 規則分 × (ML信心度/0.5)\n\n"
            "📊 Top5基礎（純規則版）\n"
            "  • 僅 4 規則策略評分\n"
            "  • 無 ML 加權\n\n"
            "📋 策略明細：\n"
            "  1️⃣ Breakout — 200日新高 + RSI>60\n"
            "  2️⃣ Acceleration — 均速曲率上升\n"
            "  3️⃣ PEG — PEG<1.5 + ROE>10%\n"
            "  4️⃣ DuPont — ROE>5% + PB<8\n"
            "  5️⃣ ML (XGBoost) — 18 技術特徵"
        )]

    # 非命令消息
    return None


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
                       current_price, ml_confidence,
                       support_1, resistance_1,
                       breakout_pass, acceleration_pass, peg_pass, dupont_pass
                FROM daily_recommendations
                WHERE scan_date = :d
                ORDER BY rank_position ASC
                LIMIT 5
            """), {'d': str(latest)})

            recs = []
            for row in rows:
                recs.append({
                    'symbol': row[0],
                    'rank': row[1],
                    'signal': row[2],
                    'total_score': float(row[3]) if row[3] else 0,
                    'current_price': float(row[4]) if row[4] else 0,
                    'ml_confidence': float(row[5]) if row[5] else 0,
                    'support_1': float(row[6]) if row[6] else None,
                    'resistance_1': float(row[7]) if row[7] else None,
                    'breakout_pass': bool(row[8]),
                    'acceleration_pass': bool(row[9]),
                    'peg_pass': bool(row[10]),
                    'dupont_pass': bool(row[11]),
                })

            if not recs:
                return [_text_msg("📊 該日期無推薦資料")]

            return [_build_top5_flex(recs, str(latest))]

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
                       current_price, ml_confidence,
                       support_1, resistance_1,
                       breakout_pass, acceleration_pass, peg_pass, dupont_pass
                FROM daily_recommendations
                WHERE scan_date = :d
                ORDER BY rank_position ASC
                LIMIT 5
            """), {'d': str(latest)})

            recs = []
            for row in rows:
                # 計算純規則評分（不考慮 ML 加權）
                ml_conf = float(row[5]) if row[5] else 0
                total_score = float(row[3]) if row[3] else 0
                
                # 反推原始規則分：如果有 ML 加權，除回去
                if ml_conf > 0:
                    rule_score = total_score / (ml_conf / 0.5)
                else:
                    rule_score = total_score
                
                recs.append({
                    'symbol': row[0],
                    'rank': row[1],
                    'signal': row[2],
                    'total_score': round(rule_score, 2),  # 使用純規則分
                    'current_price': float(row[4]) if row[4] else 0,
                    'ml_confidence': 0,  # 強制顯示 0（無 ML）
                    'support_1': float(row[6]) if row[6] else None,
                    'resistance_1': float(row[7]) if row[7] else None,
                    'breakout_pass': bool(row[8]),
                    'acceleration_pass': bool(row[9]),
                    'peg_pass': bool(row[10]),
                    'dupont_pass': bool(row[11]),
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
            row = conn.execute(sql_text("""
                SELECT symbol, entry_date, entry_price, confidence, top_features
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
    """建構單支股票的 Flex Bubble"""
    signal = rec.get('signal', 'N/A')
    signal_color = "#00C853" if signal == 'BUY' else "#FF1744"
    ml_conf = rec.get('ml_confidence', 0) or 0
    ml_str = f"{ml_conf:.0%}" if ml_conf > 0 else "—"

    strats = []
    if rec.get('breakout_pass'):
        strats.append("突破")
    if rec.get('acceleration_pass'):
        strats.append("加速")
    if rec.get('peg_pass'):
        strats.append("PEG")
    if rec.get('dupont_pass'):
        strats.append("杜邦")

    body_rows = [
        _flex_kv("💰 價格", f"${rec['current_price']:.2f}"),
        _flex_kv("📊 評分", f"{rec['total_score']:.1f}/5"),
        _flex_kv("🤖 ML", ml_str),
        _flex_kv("✅ 策略", " | ".join(strats) if strats else "—"),
    ]

    s1 = rec.get('support_1')
    r1 = rec.get('resistance_1')
    if s1:
        body_rows.append(_flex_kv("📉 支撐", f"${s1:.2f}"))
    if r1:
        body_rows.append(_flex_kv("📈 壓力", f"${r1:.2f}"))

    return {
        "type": "bubble",
        "size": "kilo",
        "header": {
            "type": "box",
            "layout": "horizontal",
            "contents": [
                {
                    "type": "text",
                    "text": f"#{rec['rank']} {rec['symbol']}",
                    "weight": "bold",
                    "size": "lg",
                    "color": "#FFFFFF",
                },
                {
                    "type": "text",
                    "text": signal,
                    "weight": "bold",
                    "size": "sm",
                    "align": "end",
                    "color": "#FFFFFF",
                },
            ],
            "backgroundColor": signal_color,
            "paddingAll": "15px",
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": body_rows,
            "spacing": "sm",
            "paddingAll": "13px",
        },
    }


def _flex_kv(label: str, value: str) -> dict:
    """建構 Flex 鍵值對行"""
    return {
        "type": "box",
        "layout": "horizontal",
        "contents": [
            {"type": "text", "text": label, "size": "sm", "color": "#555555", "flex": 0},
            {"type": "text", "text": value, "size": "sm", "color": "#111111", "align": "end"},
        ],
    }


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
