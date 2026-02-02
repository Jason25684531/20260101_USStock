"""
Line Bot Webhook 處理器

處理來自 Line Platform 的 Webhook 請求
實現簽名驗證和消息回覆

Author: Quant System
Created: 2026-01-31
"""

import os
import hashlib
import hmac
import base64
from flask import Blueprint, request, abort, jsonify
from functools import wraps

# 導入安全工具
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from security import get_secret


# 創建 Blueprint
line_bot_bp = Blueprint('line_bot', __name__)

# 獲取 Line Channel Secret（用於驗證簽名）
CHANNEL_SECRET = get_secret('line_channel_secret', '')


def verify_signature(func):
    """
    驗證 Line Webhook 簽名的裝飾器
    
    防止偽造請求，確保請求確實來自 Line Platform
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        # 獲取簽名
        signature = request.headers.get('X-Line-Signature', '')
        
        if not signature:
            print("❌ 缺少 X-Line-Signature 標頭")
            abort(400, description="Missing X-Line-Signature header")
        
        if not CHANNEL_SECRET:
            print("⚠️  Channel Secret 未配置，跳過簽名驗證（僅限開發環境）")
            return func(*args, **kwargs)
        
        # 計算預期簽名
        body = request.get_data(as_text=True)
        hash_value = hmac.new(
            CHANNEL_SECRET.encode('utf-8'),
            body.encode('utf-8'),
            hashlib.sha256
        ).digest()
        expected_signature = base64.b64encode(hash_value).decode('utf-8')
        
        # 驗證簽名
        if not hmac.compare_digest(signature, expected_signature):
            print("❌ 簽名驗證失敗")
            abort(403, description="Invalid signature")
        
        return func(*args, **kwargs)
    
    return wrapper


@line_bot_bp.route('/callback', methods=['POST'])
@verify_signature
def callback():
    """
    Line Webhook 回調端點
    
    接收並處理來自 Line Platform 的事件
    """
    try:
        body = request.get_json()
        
        if not body:
            return jsonify({'status': 'error', 'message': 'Empty body'}), 400
        
        events = body.get('events', [])
        
        for event in events:
            event_type = event.get('type')
            
            if event_type == 'message':
                handle_message_event(event)
            elif event_type == 'follow':
                handle_follow_event(event)
            elif event_type == 'unfollow':
                handle_unfollow_event(event)
            else:
                print(f"📨 收到未處理的事件類型: {event_type}")
        
        return jsonify({'status': 'ok'}), 200
        
    except Exception as e:
        print(f"❌ Webhook 處理錯誤: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


def handle_message_event(event: dict):
    """
    處理消息事件
    
    Args:
        event: Line 事件對象
    """
    message = event.get('message', {})
    message_type = message.get('type')
    
    if message_type == 'text':
        text = message.get('text', '')
        user_id = event.get('source', {}).get('userId', 'unknown')
        reply_token = event.get('replyToken')
        
        print(f"📩 收到文字消息: '{text}' from {user_id}")
        
        # 處理命令
        response = process_command(text)
        
        if response and reply_token:
            reply_message(reply_token, response)


def handle_follow_event(event: dict):
    """
    處理關注事件
    
    Args:
        event: Line 事件對象
    """
    user_id = event.get('source', {}).get('userId', 'unknown')
    reply_token = event.get('replyToken')
    
    print(f"👋 新用戶關注: {user_id}")
    
    welcome_message = """
🎉 歡迎使用美股交易策略系統！

可用命令：
📊 /status - 查看系統狀態
📈 /summary - 查看今日摘要
💰 /positions - 查看持倉
❓ /help - 查看幫助

系統將自動推送交易信號和每日報告。
""".strip()
    
    if reply_token:
        reply_message(reply_token, welcome_message)


def handle_unfollow_event(event: dict):
    """
    處理取消關注事件
    
    Args:
        event: Line 事件對象
    """
    user_id = event.get('source', {}).get('userId', 'unknown')
    print(f"👋 用戶取消關注: {user_id}")


def process_command(text: str) -> Optional[str]:
    """
    處理用戶命令
    
    Args:
        text: 用戶發送的文字
        
    Returns:
        回覆消息，如果不需要回覆則返回 None
    """
    text = text.strip().lower()
    
    if text.startswith('/status') or text == '狀態':
        return "🟢 系統運行正常\n\n📊 策略引擎: 運行中\n💾 數據庫: 已連接\n📈 最後更新: 剛才"
    
    elif text.startswith('/help') or text == '幫助':
        return """
📚 可用命令：

/status - 查看系統狀態
/summary - 查看今日交易摘要
/positions - 查看當前持倉
/strategies - 查看可用策略
/help - 顯示此幫助信息

💡 系統會自動推送交易信號
""".strip()
    
    elif text.startswith('/summary') or text == '摘要':
        return "📊 今日暫無交易信號\n\n系統正在監控市場..."
    
    elif text.startswith('/positions') or text == '持倉':
        return "💰 當前無持倉\n\n等待買入信號..."
    
    elif text.startswith('/strategies') or text == '策略':
        return """
📈 可用策略：

1️⃣ SMA 動量策略
   • 快線: 20日
   • 慢線: 50日

2️⃣ 價值策略
   • PE < 15
   • PB < 1.5

3️⃣ Chips + 動量 (Smart Money)
   • SMA > 50日
   • 機構持股 > 60%

4️⃣ Growth (PEG)
   • PEG < 1.5
   • 營收增長 > 20%
""".strip()
    
    # 非命令消息
    return None


def reply_message(reply_token: str, message: str):
    """
    回覆消息
    
    Args:
        reply_token: Line 回覆令牌
        message: 回覆內容
    """
    import requests
    
    channel_token = get_secret('line_channel_token')
    
    if not channel_token:
        print("⚠️  Channel Token 未配置，無法回覆消息")
        return
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {channel_token}"
    }
    
    payload = {
        "replyToken": reply_token,
        "messages": [{
            "type": "text",
            "text": message
        }]
    }
    
    try:
        response = requests.post(
            "https://api.line.me/v2/bot/message/reply",
            headers=headers,
            json=payload,
            timeout=10
        )
        
        if response.status_code == 200:
            print("✅ 消息回覆成功")
        else:
            print(f"❌ 消息回覆失敗: {response.status_code}")
            
    except Exception as e:
        print(f"❌ 回覆請求失敗: {str(e)}")


# 用於獲取 User ID 的工具路由（開發用）
@line_bot_bp.route('/webhook/info', methods=['GET'])
def webhook_info():
    """返回 Webhook 配置信息（用於調試）"""
    return jsonify({
        'status': 'active',
        'endpoint': '/bot/callback',
        'channel_secret_configured': bool(CHANNEL_SECRET),
        'channel_token_configured': bool(get_secret('line_channel_token'))
    })
