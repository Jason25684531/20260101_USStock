"""
Flask Web Application for US Stock Trading Dashboard

提供 API 端點來查詢回測結果和顯示權益曲線
包含 Line Bot Webhook 處理

Author: Quant System
Created: 2025-12-31
Updated: 2026-01-31 - 添加 Line Bot 整合
"""
import os
from pathlib import Path
from typing import Optional
from flask import Flask, render_template, jsonify
from flask_httpauth import HTTPBasicAuth
from werkzeug.security import check_password_hash, generate_password_hash
from sqlalchemy import create_engine, text
from datetime import datetime

# 導入 Line Bot Blueprint
from bot import line_bot_bp

app = Flask(__name__)
auth = HTTPBasicAuth()

# 註冊 Line Bot Blueprint
app.register_blueprint(line_bot_bp, url_prefix='/bot')

# ============================================
# 安全工具函數（避免重複導入問題）
# ============================================
SECRETS_PATH = Path("/run/secrets")


def get_secret(secret_name: str, default: Optional[str] = None) -> Optional[str]:
    """從 Docker Secrets 或環境變量獲取密鑰"""
    secret_file = SECRETS_PATH / secret_name
    if secret_file.exists():
        try:
            return secret_file.read_text().strip()
        except (IOError, PermissionError):
            pass
    
    if SECRETS_PATH.exists():
        return default
    
    return os.environ.get(secret_name.upper(), default)


# ============================================
# 數據庫配置
# ============================================
DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_PORT = os.getenv('DB_PORT', '3306')
DB_USER = os.getenv('DB_USER', 'root')
DB_PASS = get_secret('db_root_password', default=os.getenv('DB_PASSWORD', 'rootpassword'))
DB_NAME = os.getenv('DB_NAME', 'usstock')

# 建立數據庫連接
connection_string = (
    f"mysql+mysqlconnector://{DB_USER}:{DB_PASS}@"
    f"{DB_HOST}:{DB_PORT}/{DB_NAME}?charset=utf8mb4"
)
engine = create_engine(connection_string, echo=False)

# ============================================
# Web 認證配置
# ============================================
WEB_PASSWORD = get_secret('web_password', default='admin123')
WEB_PASSWORD_HASH = generate_password_hash(WEB_PASSWORD)


@auth.verify_password
def verify_password(username, password):
    """驗證用戶名和密碼"""
    if username == 'admin' and check_password_hash(WEB_PASSWORD_HASH, password):
        return username
    return None


# ============================================
# 頁面路由
# ============================================
@app.route('/')
@auth.login_required
def index():
    """首頁 - 顯示儀表板"""
    return render_template('index.html')


@app.route('/api/strategies')
@auth.login_required
def get_strategies():
    """
    獲取所有策略運行記錄
    
    Returns:
        JSON 列表，包含所有回測運行的信息
    """
    try:
        with engine.connect() as conn:
            query = text("""
                SELECT 
                    id,
                    strategy_name,
                    start_date,
                    end_date,
                    total_return,
                    sharpe_ratio,
                    max_drawdown,
                    created_at
                FROM backtest_runs
                ORDER BY created_at DESC
            """)
            
            result = conn.execute(query)
            
            strategies = []
            for row in result:
                strategies.append({
                    'id': row[0],
                    'strategy_name': row[1],
                    'start_date': str(row[2]),
                    'end_date': str(row[3]),
                    'total_return': float(row[4]) if row[4] else 0,
                    'sharpe_ratio': float(row[5]) if row[5] else 0,
                    'max_drawdown': float(row[6]) if row[6] else 0,
                    'created_at': row[7].strftime('%Y-%m-%d %H:%M:%S') if row[7] else None
                })
            
            return jsonify(strategies)
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/run/<int:run_id>/equity')
@auth.login_required
def get_equity_curve(run_id):
    """
    獲取指定回測運行的權益曲線
    
    Args:
        run_id: 回測運行 ID
        
    Returns:
        JSON 對象，包含日期和權益值數組
    """
    try:
        with engine.connect() as conn:
            query = text("""
                SELECT 
                    date,
                    equity_value
                FROM equity_curve
                WHERE run_id = :run_id
                ORDER BY date ASC
            """)
            
            result = conn.execute(query, {'run_id': run_id})
            
            dates = []
            values = []
            
            for row in result:
                dates.append(str(row[0]))
                values.append(float(row[1]))
            
            return jsonify({
                'dates': dates,
                'values': values
            })
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/run/<int:run_id>/trades')
@auth.login_required
def get_trades(run_id):
    """
    獲取指定回測運行的交易記錄
    
    Args:
        run_id: 回測運行 ID
        
    Returns:
        JSON 列表，包含所有交易記錄
    """
    try:
        with engine.connect() as conn:
            query = text("""
                SELECT 
                    symbol,
                    entry_date,
                    exit_date,
                    entry_price,
                    exit_price,
                    pnl
                FROM trade_logs
                WHERE run_id = :run_id
                ORDER BY entry_date ASC
            """)
            
            result = conn.execute(query, {'run_id': run_id})
            
            trades = []
            for row in result:
                trades.append({
                    'symbol': row[0],
                    'entry_date': str(row[1]) if row[1] else None,
                    'exit_date': str(row[2]) if row[2] else None,
                    'entry_price': float(row[3]) if row[3] else 0,
                    'exit_price': float(row[4]) if row[4] else 0,
                    'pnl': float(row[5]) if row[5] else 0
                })
            
            return jsonify(trades)
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/health')
def health():
    """健康檢查端點（公開，供 Docker 使用）"""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        
        return jsonify({
            'status': 'healthy',
            'timestamp': datetime.now().isoformat(),
            'database': 'connected',
            'line_bot': 'enabled'
        })
    except Exception as e:
        return jsonify({
            'status': 'unhealthy',
            'timestamp': datetime.now().isoformat(),
            'database': 'disconnected',
            'error': str(e)
        }), 500


# ============================================
# Line Bot 通知 API（供策略引擎調用）
# ============================================
@app.route('/api/notify/signal', methods=['POST'])
def notify_signal():
    """
    接收策略引擎的交易信號並推送到 Line
    
    這是一個內部 API，供策略引擎調用
    """
    from flask import request
    from bot.handler import get_secret
    import requests
    
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    
    channel_token = get_secret('line_channel_token')
    user_id = get_secret('line_user_id')
    
    if not channel_token or not user_id:
        return jsonify({'error': 'Line Bot not configured'}), 503
    
    # 構建消息
    action_emoji = {"BUY": "🟢", "SELL": "🔴", "HOLD": "🟡"}.get(data.get('action', '').upper(), "⚪")
    
    message = f"""
{action_emoji} 交易信號 {action_emoji}

📊 股票: {data.get('symbol', 'N/A')}
📈 動作: {data.get('action', 'N/A').upper()}
💰 價格: ${data.get('price', 0):,.2f}
🎯 策略: {data.get('strategy', 'Unknown')}
📝 原因: {data.get('reason', 'N/A')}

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
""".strip()
    
    # 推送消息
    try:
        response = requests.post(
            "https://api.line.me/v2/bot/message/push",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {channel_token}"
            },
            json={
                "to": user_id,
                "messages": [{"type": "text", "text": message}]
            },
            timeout=10
        )
        
        if response.status_code == 200:
            return jsonify({'status': 'sent'})
        else:
            return jsonify({'error': f'Line API error: {response.status_code}'}), 500
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    print(f"🚀 啟動 Flask 儀表板...")
    print(f"   數據庫: {DB_HOST}:{DB_PORT}/{DB_NAME}")
    print(f"   訪問地址: http://0.0.0.0:5000")
    print(f"   Line Bot Webhook: /bot/callback")
    print(f"   認證: 用戶名='admin'")
    app.run(host='0.0.0.0', port=5000, debug=True)