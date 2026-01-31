"""
Flask Web Application for US Stock Trading Dashboard

提供 API 端點來查詢回測結果和顯示權益曲線
"""
import os
from flask import Flask, render_template, jsonify
from sqlalchemy import create_engine, text
from datetime import datetime

app = Flask(__name__)

# 數據庫配置
DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_PORT = os.getenv('DB_PORT', '3306')
DB_USER = os.getenv('DB_USER', 'root')
DB_PASS = os.getenv('DB_PASSWORD', 'rootpassword')
DB_NAME = os.getenv('DB_NAME', 'usstock')

# 建立數據庫連接
connection_string = (
    f"mysql+mysqlconnector://{DB_USER}:{DB_PASS}@"
    f"{DB_HOST}:{DB_PORT}/{DB_NAME}?charset=utf8mb4"
)
engine = create_engine(connection_string, echo=False)


@app.route('/')
def index():
    """首頁 - 顯示儀表板"""
    return render_template('index.html')


@app.route('/api/strategies')
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
    """健康檢查端點"""
    try:
        # 測試數據庫連接
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        
        return jsonify({
            'status': 'healthy',
            'timestamp': datetime.now().isoformat(),
            'database': 'connected'
        })
    except Exception as e:
        return jsonify({
            'status': 'unhealthy',
            'timestamp': datetime.now().isoformat(),
            'database': 'disconnected',
            'error': str(e)
        }), 500


if __name__ == '__main__':
    print(f"🚀 啟動 Flask 儀表板...")
    print(f"   數據庫: {DB_HOST}:{DB_PORT}/{DB_NAME}")
    print(f"   訪問地址: http://0.0.0.0:5000")
    app.run(host='0.0.0.0', port=5000, debug=True)