"""
Flask Web Application for US Stock Trading Dashboard

提供 API 端點來查詢回測結果和顯示權益曲線
包含 Line Bot Webhook 處理

Author: Quant System
Created: 2025-12-31
Updated: 2026-01-31 - 添加 Line Bot 整合
"""
import os
from flask import Flask, render_template, jsonify
from flask_httpauth import HTTPBasicAuth
from werkzeug.security import check_password_hash, generate_password_hash
from sqlalchemy import text
from datetime import datetime

# 導入安全工具和 Line Bot Blueprint
from security import get_secret
from bot import line_bot_bp
from db import get_db_config, get_engine

app = Flask(__name__)
auth = HTTPBasicAuth()

# 註冊 Line Bot Blueprint
# Webhook 端點: /callback (LINE Platform 呼叫)
# Debug 端點: /webhook/info
app.register_blueprint(line_bot_bp)


# ============================================
# 數據庫配置
# ============================================
DB_CONFIG = get_db_config()
engine = get_engine(DB_CONFIG, echo=False)

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
# ML Model Status API
# ============================================
@app.route('/api/ml_status')
@auth.login_required
def get_ml_status():
    """
    獲取 ML 模型狀態：最近交易的置信度和 top_features

    Returns:
        JSON 對象：
        {
            "model_loaded": true,
            "feature_importance": [...],     # 來自模型文件（如果可用）
            "recent_signals": [...]          # 最近 20 筆 trade_logs 帶 confidence
        }
    """
    import json as _json

    result = {
        'model_loaded': False,
        'feature_importance': [],
        'recent_signals': [],
    }

    # 1. 嘗試讀取模型的 feature importance（從 model.pkl）
    try:
        import pickle
        from pathlib import Path

        model_path = Path('/app/data/model.pkl')
        # 也嘗試本機開發路徑
        if not model_path.exists():
            model_path = Path(__file__).parent.parent / 'data' / 'model.pkl'

        if model_path.exists():
            with open(model_path, 'rb') as f:
                model_data = pickle.load(f)
            fi = model_data.get('feature_importance')
            if fi is not None and hasattr(fi, 'head'):
                top = fi.head(10)
                result['feature_importance'] = [
                    {'feature': row['feature'], 'importance': round(float(row['importance']), 4)}
                    for _, row in top.iterrows()
                ]
            result['model_loaded'] = True
    except Exception:
        pass  # 模型不存在也不影響 API

    # 2. 從 trade_logs 拉最近帶 confidence 的交易信號
    try:
        with engine.connect() as conn:
            query = text("""
                SELECT
                    symbol,
                    entry_date,
                    entry_price,
                    confidence,
                    top_features
                FROM trade_logs
                WHERE confidence IS NOT NULL
                ORDER BY entry_date DESC, id DESC
                LIMIT 20
            """)
            rows = conn.execute(query)
            for row in rows:
                sig = {
                    'symbol': row[0],
                    'entry_date': str(row[1]) if row[1] else None,
                    'entry_price': float(row[2]) if row[2] else 0,
                    'confidence': float(row[3]) if row[3] else None,
                    'top_features': _json.loads(row[4]) if row[4] else None,
                }
                result['recent_signals'].append(sig)
    except Exception as e:
        result['db_error'] = str(e)

    return jsonify(result)


# ============================================
# 每日選股推薦 API
# ============================================
@app.route('/api/recommendations')
@auth.login_required
def get_recommendations():
    """
    獲取最新一日的選股推薦結果

    Query params:
        date: 指定日期 (YYYY-MM-DD), 預設最新
        limit: 筆數 (預設 10)

    Returns:
        JSON 列表: [{rank, symbol, signal, total_score, current_price, ...}]
    """
    from flask import request as flask_request

    req_date = flask_request.args.get('date')
    limit = flask_request.args.get('limit', 10, type=int)

    try:
        with engine.connect() as conn:
            if req_date:
                date_filter = "scan_date = :target_date"
                params = {'target_date': req_date, 'limit': limit}
            else:
                # 取最新日期
                latest = conn.execute(text(
                    "SELECT MAX(scan_date) FROM daily_recommendations"
                )).scalar()
                if not latest:
                    return jsonify([])
                date_filter = "scan_date = :target_date"
                params = {'target_date': str(latest), 'limit': limit}

            query = text(f"""
                SELECT
                    scan_date, symbol, rank_position, signal_type, total_score,
                    breakout_pass, acceleration_pass, peg_pass, dupont_pass,
                    ml_confidence, current_price,
                    support_1, support_2, resistance_1, resistance_2,
                    pe_ratio, peg_ratio, pb_ratio, roe,
                    strategy_details, created_at
                FROM daily_recommendations
                WHERE {date_filter}
                ORDER BY rank_position ASC
                LIMIT :limit
            """)

            result = conn.execute(query, params)
            recs = []
            for row in result:
                recs.append({
                    'scan_date': str(row[0]),
                    'symbol': row[1],
                    'rank': row[2],
                    'signal': row[3],
                    'total_score': float(row[4]) if row[4] else 0,
                    'breakout_pass': bool(row[5]),
                    'acceleration_pass': bool(row[6]),
                    'peg_pass': bool(row[7]),
                    'dupont_pass': bool(row[8]),
                    'ml_confidence': float(row[9]) if row[9] else None,
                    'current_price': float(row[10]) if row[10] else 0,
                    'support_1': float(row[11]) if row[11] else None,
                    'support_2': float(row[12]) if row[12] else None,
                    'resistance_1': float(row[13]) if row[13] else None,
                    'resistance_2': float(row[14]) if row[14] else None,
                    'pe_ratio': float(row[15]) if row[15] else None,
                    'peg_ratio': float(row[16]) if row[16] else None,
                    'pb_ratio': float(row[17]) if row[17] else None,
                    'roe': float(row[18]) if row[18] else None,
                    'strategy_details': row[19],
                    'created_at': row[20].strftime('%Y-%m-%d %H:%M:%S') if row[20] else None,
                })

            return jsonify(recs)

    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    port = int(os.getenv('WEB_PORT', '6688'))
    print(f"🚀 啟動 Flask 儀表板...")
    print(f"   DB: {DB_CONFIG['host']}:{DB_CONFIG['port']}:{DB_CONFIG['name']}")
    print(f"   訪問地址: http://0.0.0.0:{port}")
    print(f"   Line Bot Webhook: /callback")
    print(f"   認證: 用戶名='admin'")
    app.run(host='0.0.0.0', port=port, debug=True)