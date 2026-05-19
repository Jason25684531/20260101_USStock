"""
Flask Web Application for US Stock Trading Dashboard

提供 API 端點來查詢回測結果和顯示權益曲線
包含 Line Bot Webhook 處理

Author: Quant System
Created: 2025-12-31
Updated: 2026-01-31 - 添加 Line Bot 整合
"""
import os
import json
import logging
import sys
import threading
from pathlib import Path
import pandas as pd
from dotenv import load_dotenv
from flask import Flask, render_template, jsonify, request
from flask_httpauth import HTTPBasicAuth
from werkzeug.security import check_password_hash, generate_password_hash
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from datetime import datetime

load_dotenv()

# 導入安全工具和 Line Bot Blueprint
from security import get_secret
from bot import line_bot_bp
from db import get_db_config, get_engine, table_exists, column_exists

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
APP_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = APP_ROOT.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

STRATEGIES_SRC_CANDIDATES = (
    APP_ROOT / 'strategies_src',
    PROJECT_ROOT / 'strategies' / 'src',
)
STRATEGIES_SRC_ROOT = next((path for path in STRATEGIES_SRC_CANDIDATES if path.exists()), STRATEGIES_SRC_CANDIDATES[0])
if str(STRATEGIES_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(STRATEGIES_SRC_ROOT))

ONECLICK_BACKTEST_SCRIPT = STRATEGIES_SRC_ROOT / 'main.py'

try:
    from utils.runtime_config import find_existing_model_path
except ImportError:
    from strategies.src.utils.runtime_config import find_existing_model_path


# Aliases for backward compatibility (previously defined locally)
_table_exists = table_exists
_column_exists = column_exists

RECOVERABLE_DASHBOARD_DB_ERROR_CODES = {1049, 1054, 1146, 2003}
RECOVERABLE_DASHBOARD_DB_ERROR_MARKERS = (
    "can't connect to mysql server",
    "unknown column",
    "doesn't exist",
    "unknown table",
    "connection refused",
)
CHART_PERIOD_LABELS = {'d': '日線', 'w': '週線', 'm': '月線'}
CHART_HISTORY_LIMITS = {'d': 380, 'w': 260, 'm': 180}
CHART_FETCH_LIMITS = {'d': 420, 'w': 1500, 'm': 3000}


def _env_positive_int(name, default):
    try:
        return max(int(os.getenv(name, default)), 1)
    except (TypeError, ValueError):
        return default


DEFAULT_ONECLICK_BACKTEST_SYMBOLS = tuple(
    symbol.strip().upper()
    for symbol in os.getenv('ONECLICK_BACKTEST_SYMBOLS', 'AAPL,MSFT,NVDA,GOOGL').split(',')
    if symbol.strip()
)
DEFAULT_ONECLICK_BACKTEST_MONTHS = _env_positive_int('ONECLICK_BACKTEST_MONTHS', 6)
DEFAULT_ONECLICK_BACKTEST_TOP_N = _env_positive_int('ONECLICK_BACKTEST_TOP_N', 5)
MAX_FORM_BACKTEST_SYMBOLS = 60
NEWS_TRANSLATION_MODEL = os.getenv('NEWS_TRANSLATION_MODEL', 'gemini-2.5-flash')
NEWS_TRANSLATION_FALLBACK_MODEL = os.getenv('NEWS_TRANSLATION_FALLBACK_MODEL', 'gemini-2.0-flash')
INSTITUTIONAL_FLOW_TABLE_CANDIDATES = (
    {
        'table': 'institutional_trading_daily',
        'date': ['date', 'trade_date', 'data_date'],
        'foreign_net': ['foreign_net', 'foreign_net_shares', 'foreign_net_volume'],
        'foreign_buy': ['foreign_buy', 'foreign_buy_shares'],
        'foreign_sell': ['foreign_sell', 'foreign_sell_shares'],
        'trust_net': ['investment_trust_net', 'trust_net', 'institutional_trust_net'],
        'trust_buy': ['investment_trust_buy', 'trust_buy'],
        'trust_sell': ['investment_trust_sell', 'trust_sell'],
        'dealer_net': ['dealer_net', 'self_dealer_net', 'proprietary_trader_net'],
        'dealer_buy': ['dealer_buy', 'self_dealer_buy'],
        'dealer_sell': ['dealer_sell', 'self_dealer_sell'],
    },
    {
        'table': 'institutional_flows',
        'date': ['date', 'trade_date', 'data_date'],
        'foreign_net': ['foreign_net'],
        'foreign_buy': ['foreign_buy'],
        'foreign_sell': ['foreign_sell'],
        'trust_net': ['trust_net', 'investment_trust_net'],
        'trust_buy': ['trust_buy', 'investment_trust_buy'],
        'trust_sell': ['trust_sell', 'investment_trust_sell'],
        'dealer_net': ['dealer_net'],
        'dealer_buy': ['dealer_buy'],
        'dealer_sell': ['dealer_sell'],
    },
)
_NEWS_TRANSLATION_CACHE = {}
_backtest_job_lock = threading.Lock()
_backtest_job_state = {
    'status': 'idle',
    'message': '尚未執行一鍵回測',
    'started_at': None,
    'finished_at': None,
    'last_run_id': None,
    'last_strategy_name': None,
    'output_tail': [],
}


def _extract_db_error_code(error):
    """Extract a database error code from wrapped DB exceptions when available."""
    candidates = [error, getattr(error, 'orig', None)]
    for candidate in candidates:
        if candidate is None:
            continue

        errno = getattr(candidate, 'errno', None)
        if isinstance(errno, int):
            return errno

        args = getattr(candidate, 'args', ())
        for value in args:
            if isinstance(value, int):
                return value
    return None


def _is_recoverable_dashboard_error(error):
    """Return True when a dashboard read endpoint can safely degrade."""
    if not isinstance(error, SQLAlchemyError):
        return False

    error_code = _extract_db_error_code(error)
    if error_code in RECOVERABLE_DASHBOARD_DB_ERROR_CODES:
        return True

    message = str(error).lower()
    return any(marker in message for marker in RECOVERABLE_DASHBOARD_DB_ERROR_MARKERS)


def _dashboard_degraded_response(endpoint_name, payload, error):
    """Return a stable response payload for recoverable dashboard data failures."""
    body = dict(payload)
    body['degraded'] = True
    body['warning'] = f'{endpoint_name} data temporarily unavailable'
    app.logger.warning('%s degraded: %s', endpoint_name, error)
    return jsonify(body)


def _dashboard_failure_response(endpoint_name, error):
    """Return a structured error response for unrecoverable failures."""
    app.logger.exception('%s failed', endpoint_name)
    return jsonify({'error': f'{endpoint_name} failed'}), 500


def _handle_dashboard_exception(endpoint_name, payload, error):
    """Convert known read-only dashboard failures into stable empty states."""
    if _is_recoverable_dashboard_error(error):
        return _dashboard_degraded_response(endpoint_name, payload, error)
    return _dashboard_failure_response(endpoint_name, error)


def _build_empty_correlation_payload(reason: str = ""):
    return {
        'window_days': 60,
        'symbols': [],
        'matrix': [],
        'reason': reason,
    }


def _load_latest_sector_map(conn, symbols):
    if not symbols or not _table_exists(conn, 'stock_fundamentals') or not _column_exists(conn, 'stock_fundamentals', 'sector'):
        return {}

    placeholders = ", ".join(f":s{i}" for i in range(len(symbols)))
    params = {f"s{i}": symbol for i, symbol in enumerate(symbols)}
    query = text(f"""
        SELECT sf.symbol, sf.sector
        FROM stock_fundamentals sf
        INNER JOIN (
            SELECT symbol, MAX(data_date) AS latest_data_date
            FROM stock_fundamentals
            WHERE symbol IN ({placeholders})
            GROUP BY symbol
        ) latest
          ON sf.symbol = latest.symbol
         AND sf.data_date = latest.latest_data_date
        WHERE sf.symbol IN ({placeholders})
    """)

    sector_map = {}
    for row in conn.execute(query, params):
        sector_map[str(row[0]).upper()] = row[1]
    return sector_map


def _load_portfolio_state_holdings(conn):
    if not _table_exists(conn, 'trade_logs'):
        return []

    rows = conn.execute(text("""
        SELECT symbol, entry_date, entry_price
        FROM trade_logs
        WHERE exit_date IS NULL
        ORDER BY entry_date DESC, id DESC
    """))
    holdings = [
        {
            'symbol': str(row[0]).upper(),
            'entry_date': str(row[1]) if row[1] else None,
            'entry_price': float(row[2]) if row[2] is not None else None,
        }
        for row in rows
    ]
    if not holdings:
        return []

    symbols = [holding['symbol'] for holding in holdings]
    sector_map = _load_latest_sector_map(conn, symbols)
    if len(sector_map) < len(symbols):
        from constants import SECTOR_MAP_FALLBACK
        for symbol in symbols:
            sector_map.setdefault(symbol, SECTOR_MAP_FALLBACK.get(symbol, 'Unknown'))

    for holding in holdings:
        holding['sector'] = sector_map.get(holding['symbol'], 'Unknown')
    return holdings


def _load_price_history_for_symbols(symbols, lookback_days: int = 120):
    if not symbols:
        return {}

    placeholders = ", ".join(f":s{i}" for i in range(len(symbols)))
    params = {f"s{i}": symbol for i, symbol in enumerate(symbols)}
    safe_lookback_days = max(int(lookback_days), 1)
    query = text(f"""
        SELECT symbol, date, close
        FROM price_data_v2
        WHERE symbol IN ({placeholders})
          AND date >= DATE_SUB(CURDATE(), INTERVAL {safe_lookback_days} DAY)
        ORDER BY symbol ASC, date ASC
    """)

    price_df = pd.read_sql(query, con=engine, params=params)
    if price_df.empty:
        return {}

    price_df['date'] = pd.to_datetime(price_df['date'])
    history = {}
    for symbol, group in price_df.groupby('symbol'):
        history[str(symbol).upper()] = group[['date', 'close']].set_index('date')
    return history


def _build_universe_sync_payload(conn):
    empty_payload = {
        'universe_code': None,
        'status': 'unavailable',
        'processed_symbols': 0,
        'total_symbols': 0,
        'progress_pct': 0.0,
        'finished_at': None,
        'error_message': None,
    }
    if not _table_exists(conn, 'universe_sync_runs'):
        return empty_payload

    row = conn.execute(text("""
        SELECT universe_code, status, processed_symbols, total_symbols, finished_at, error_message
        FROM universe_sync_runs
        ORDER BY created_at DESC, id DESC
        LIMIT 1
    """)).mappings().first()
    if not row:
        return empty_payload

    total_symbols = int(row['total_symbols'] or 0)
    processed_symbols = int(row['processed_symbols'] or 0)
    progress_pct = round((processed_symbols / total_symbols) * 100, 1) if total_symbols > 0 else 0.0
    return {
        'universe_code': row['universe_code'],
        'status': row['status'],
        'processed_symbols': processed_symbols,
        'total_symbols': total_symbols,
        'progress_pct': progress_pct,
        'finished_at': str(row['finished_at']) if row['finished_at'] else None,
        'error_message': row['error_message'],
    }

# ============================================
# Web 認證配置
# ============================================
WEB_PASSWORD = get_secret('web_password', default='admin123')
WEB_PASSWORD_HASH = generate_password_hash(WEB_PASSWORD)
WEB_DISABLE_AUTH = os.getenv('WEB_DISABLE_AUTH', 'false').lower() in ('1', 'true', 'yes', 'on')


@auth.verify_password
def verify_password(username, password):
    """驗證用戶名和密碼"""
    if WEB_DISABLE_AUTH:
        return username or 'anonymous'

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
    empty_payload = []

    try:
        with engine.connect() as conn:
            if not _table_exists(conn, 'backtest_runs'):
                return jsonify(empty_payload)

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
        return _handle_dashboard_exception('strategies', {'strategies': empty_payload}, e)


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
    result = {
        'model_loaded': False,
        'feature_importance': [],
        'recent_signals': [],
    }

    # 1. 嘗試讀取模型的 feature importance（從 model.pkl）
    try:
        import pickle
        model_path = find_existing_model_path()

        if model_path is not None and model_path.exists():
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
            if not _table_exists(conn, 'trade_logs'):
                return jsonify(result)

            has_confidence = _column_exists(conn, 'trade_logs', 'confidence')
            has_top_features = _column_exists(conn, 'trade_logs', 'top_features')

            select_cols = ['symbol', 'entry_date', 'entry_price']
            if has_confidence:
                select_cols.append('confidence')
            if has_top_features:
                select_cols.append('top_features')

            where_clause = ' WHERE confidence IS NOT NULL' if has_confidence else ''
            query = text(f"""
                SELECT {', '.join(select_cols)}
                FROM trade_logs
                {where_clause}
                ORDER BY entry_date DESC, id DESC
                LIMIT 20
            """)
            rows = conn.execute(query)
            for row in rows:
                row_map = dict(zip(select_cols, row))
                top_features_raw = row_map.get('top_features')
                sig = {
                    'symbol': row_map.get('symbol'),
                    'entry_date': str(row_map.get('entry_date')) if row_map.get('entry_date') else None,
                    'entry_price': float(row_map.get('entry_price')) if row_map.get('entry_price') else 0,
                    'confidence': float(row_map.get('confidence')) if row_map.get('confidence') else None,
                    'top_features': json.loads(top_features_raw) if top_features_raw else None,
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
    empty_payload = {'recommendations': []}

    try:
        with engine.connect() as conn:
            if not _table_exists(conn, 'daily_recommendations'):
                return jsonify(empty_payload)

            enhanced_exprs = []
            for col in [
                'institutional_pass',
                'volume_structure_pass',
                'money_flow_pass',
                'multi_tf_momentum_pass',
                'relative_strength_pass',
                'earnings_quality_pass',
                'sector_rotation_pass',
            ]:
                if _column_exists(conn, 'daily_recommendations', col):
                    enhanced_exprs.append(col)
                else:
                    enhanced_exprs.append(f"NULL AS {col}")
            enhanced_select = ',\n                    '.join(enhanced_exprs)

            if req_date:
                date_filter = "scan_date = :target_date"
                params = {'target_date': req_date, 'limit': limit}
            else:
                # 取最新日期
                latest = conn.execute(text(
                    "SELECT MAX(scan_date) FROM daily_recommendations"
                )).scalar()
                if not latest:
                    return jsonify(empty_payload)
                date_filter = "scan_date = :target_date"
                params = {'target_date': str(latest), 'limit': limit}

            query = text(f"""
                SELECT
                    scan_date, symbol, rank_position, signal_type, total_score,
                    breakout_pass, acceleration_pass, peg_pass, dupont_pass,
                    {enhanced_select},
                    ml_confidence, current_price,
                    support_1, support_2, resistance_1, resistance_2,
                    pe_ratio, peg_ratio, pb_ratio, roe,
                    strategy_details, created_at
                FROM daily_recommendations
                WHERE {date_filter}
                ORDER BY rank_position ASC
                LIMIT :limit
            """)

            result = conn.execute(query, params).mappings()
            recs = []
            for row in result:
                recs.append({
                    'scan_date': str(row['scan_date']),
                    'symbol': row['symbol'],
                    'rank': row['rank_position'],
                    'signal': row['signal_type'],
                    'total_score': float(row['total_score']) if row['total_score'] else 0,
                    'breakout_pass': bool(row['breakout_pass']),
                    'acceleration_pass': bool(row['acceleration_pass']),
                    'peg_pass': bool(row['peg_pass']),
                    'dupont_pass': bool(row['dupont_pass']),
                    'institutional_pass': bool(row['institutional_pass']) if row['institutional_pass'] is not None else None,
                    'volume_structure_pass': bool(row['volume_structure_pass']) if row['volume_structure_pass'] is not None else None,
                    'money_flow_pass': bool(row['money_flow_pass']) if row['money_flow_pass'] is not None else None,
                    'multi_tf_momentum_pass': bool(row['multi_tf_momentum_pass']) if row['multi_tf_momentum_pass'] is not None else None,
                    'relative_strength_pass': bool(row['relative_strength_pass']) if row['relative_strength_pass'] is not None else None,
                    'earnings_quality_pass': bool(row['earnings_quality_pass']) if row['earnings_quality_pass'] is not None else None,
                    'sector_rotation_pass': bool(row['sector_rotation_pass']) if row['sector_rotation_pass'] is not None else None,
                    'ml_confidence': float(row['ml_confidence']) if row['ml_confidence'] else None,
                    'current_price': float(row['current_price']) if row['current_price'] else 0,
                    'support_1': float(row['support_1']) if row['support_1'] else None,
                    'support_2': float(row['support_2']) if row['support_2'] else None,
                    'resistance_1': float(row['resistance_1']) if row['resistance_1'] else None,
                    'resistance_2': float(row['resistance_2']) if row['resistance_2'] else None,
                    'pe_ratio': float(row['pe_ratio']) if row['pe_ratio'] else None,
                    'peg_ratio': float(row['peg_ratio']) if row['peg_ratio'] else None,
                    'pb_ratio': float(row['pb_ratio']) if row['pb_ratio'] else None,
                    'roe': float(row['roe']) if row['roe'] else None,
                    'strategy_details': row['strategy_details'],
                    'created_at': row['created_at'].strftime('%Y-%m-%d %H:%M:%S') if row['created_at'] else None,
                })

            return jsonify({'recommendations': recs})

    except Exception as e:
        return _handle_dashboard_exception('recommendations', empty_payload, e)


# ============================================
# 個股詳情 API
# ============================================
def _to_float(value):
    return float(value) if value is not None else None


def _optional_column_expr(conn, table_name, column_candidates, alias):
    for column_name in column_candidates:
        if _column_exists(conn, table_name, column_name):
            return f'{column_name} AS {alias}'
    return f'NULL AS {alias}'


def _resolve_existing_column(conn, table_name, column_candidates):
    for column_name in column_candidates:
        if _column_exists(conn, table_name, column_name):
            return column_name
    return None


def _format_trade_date(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime('%Y-%m-%d')
    if hasattr(value, 'strftime'):
        try:
            return value.strftime('%Y-%m-%d')
        except Exception:
            pass
    return str(value)[:10]


def _format_signed_number(value):
    numeric = _to_float(value)
    if numeric is None:
        return 'N/A'

    sign = '+' if numeric > 0 else ''
    abs_value = abs(numeric)
    if abs_value >= 1_000_000_000:
        formatted = f'{numeric / 1_000_000_000:.2f}B'
    elif abs_value >= 1_000_000:
        formatted = f'{numeric / 1_000_000:.2f}M'
    elif abs_value >= 1_000:
        formatted = f'{numeric:,.0f}'
    else:
        formatted = f'{numeric:.0f}'
    return f'{sign}{formatted}'


def _format_compact_number(value, suffix=''):
    numeric = _to_float(value)
    if numeric is None:
        return None

    abs_value = abs(numeric)
    if abs_value >= 1_000_000_000:
        formatted = f'{numeric / 1_000_000_000:.2f}B'
    elif abs_value >= 1_000_000:
        formatted = f'{numeric / 1_000_000:.2f}M'
    elif abs_value >= 1_000:
        formatted = f'{numeric / 1_000:.2f}K'
    else:
        formatted = f'{numeric:.0f}'
    return f'{formatted}{suffix}'


def _derive_flow_value(row, net_key, buy_key, sell_key):
    net_value = _to_float(row.get(net_key)) if net_key else None
    if net_value is not None:
        return net_value

    buy_value = _to_float(row.get(buy_key)) if buy_key else None
    sell_value = _to_float(row.get(sell_key)) if sell_key else None
    if buy_value is not None and sell_value is not None:
        return buy_value - sell_value
    return None


def _load_us_institutional_activity_snapshot(conn, symbol):
    if not _table_exists(conn, 'us_institutional_activity'):
        return None

    row = conn.execute(text("""
        SELECT snapshot_date,
               institution_report_date,
               mutualfund_report_date,
               institution_total_shares,
               institution_total_value,
               mutualfund_total_shares,
               mutualfund_total_value,
               insider_buys_6m,
               insider_sells_6m,
               insider_net_shares_6m
        FROM us_institutional_activity
        WHERE symbol = :sym
        ORDER BY snapshot_date DESC, updated_at DESC, id DESC
        LIMIT 1
    """), {'sym': symbol}).mappings().first()

    if not row:
        return None

    institution_parts = []
    institution_shares = _format_compact_number(row.get('institution_total_shares'), '股')
    institution_value = _format_money_compact(row.get('institution_total_value'))
    if institution_shares:
        institution_parts.append(institution_shares)
    if institution_value:
        institution_parts.append(institution_value)

    mutualfund_parts = []
    mutualfund_shares = _format_compact_number(row.get('mutualfund_total_shares'), '股')
    mutualfund_value = _format_money_compact(row.get('mutualfund_total_value'))
    if mutualfund_shares:
        mutualfund_parts.append(mutualfund_shares)
    if mutualfund_value:
        mutualfund_parts.append(mutualfund_value)

    insider_parts = []
    insider_net = _format_signed_number(row.get('insider_net_shares_6m'))
    insider_buys = _format_compact_number(row.get('insider_buys_6m'), '股')
    insider_sells = _format_compact_number(row.get('insider_sells_6m'), '股')
    if insider_net and insider_net != 'N/A':
        insider_parts.append(f'{insider_net}股')
    if insider_buys or insider_sells:
        insider_parts.append(f'買 {insider_buys or "N/A"} / 賣 {insider_sells or "N/A"}')

    rows = [
        {'label': '機構持股', 'value': ' / '.join(institution_parts) or 'N/A'},
        {'label': '共同基金', 'value': ' / '.join(mutualfund_parts) or 'N/A'},
        {'label': '內部人近6M', 'value': ' | '.join(insider_parts) or 'N/A'},
    ]
    if all(item['value'] == 'N/A' for item in rows):
        return None

    snapshot_date = _format_trade_date(row.get('snapshot_date'))
    report_notes = []
    institution_report_date = _format_trade_date(row.get('institution_report_date'))
    mutualfund_report_date = _format_trade_date(row.get('mutualfund_report_date'))
    if institution_report_date:
        report_notes.append(f'機構揭露 {institution_report_date}')
    if mutualfund_report_date:
        report_notes.append(f'基金揭露 {mutualfund_report_date}')

    row_summary = ' / '.join(f"{item['label']} {item['value']}" for item in rows if item['value'] != 'N/A')
    note = '資料來源: Yahoo Finance institutional_holders / mutualfund_holders / insider_purchases'
    if report_notes:
        note = f"{note}；{'，'.join(report_notes)}"

    return {
        'trade_date': snapshot_date,
        'date_label': '快照日期',
        'headline_label': '法人 / 內部人快照',
        'rows': rows,
        'source': 'us_holder_activity',
        'summary': f'{snapshot_date} 主力快照: {row_summary}' if snapshot_date else f'主力快照: {row_summary}',
        'note': note,
        'is_fallback': False,
    }


def _load_actual_institutional_flow_snapshot(conn, symbol):
    us_snapshot = _load_us_institutional_activity_snapshot(conn, symbol)
    if us_snapshot:
        return us_snapshot

    for candidate in INSTITUTIONAL_FLOW_TABLE_CANDIDATES:
        table_name = candidate['table']
        if not _table_exists(conn, table_name):
            continue
        if not _column_exists(conn, table_name, 'symbol'):
            continue

        date_column = _resolve_existing_column(conn, table_name, candidate['date'])
        if not date_column:
            continue

        resolved_columns = {
            'foreign_net': _resolve_existing_column(conn, table_name, candidate['foreign_net']),
            'foreign_buy': _resolve_existing_column(conn, table_name, candidate['foreign_buy']),
            'foreign_sell': _resolve_existing_column(conn, table_name, candidate['foreign_sell']),
            'trust_net': _resolve_existing_column(conn, table_name, candidate['trust_net']),
            'trust_buy': _resolve_existing_column(conn, table_name, candidate['trust_buy']),
            'trust_sell': _resolve_existing_column(conn, table_name, candidate['trust_sell']),
            'dealer_net': _resolve_existing_column(conn, table_name, candidate['dealer_net']),
            'dealer_buy': _resolve_existing_column(conn, table_name, candidate['dealer_buy']),
            'dealer_sell': _resolve_existing_column(conn, table_name, candidate['dealer_sell']),
        }

        if not any(resolved_columns.values()):
            continue

        select_columns = [f'{date_column} AS trade_date']
        for alias, column_name in resolved_columns.items():
            if column_name:
                select_columns.append(f'{column_name} AS {alias}')

        row = conn.execute(text(f"""
            SELECT {', '.join(select_columns)}
            FROM {table_name}
            WHERE symbol = :sym
            ORDER BY {date_column} DESC
            LIMIT 1
        """), {'sym': symbol}).mappings().first()

        if not row:
            continue

        foreign_value = _derive_flow_value(row, 'foreign_net', 'foreign_buy', 'foreign_sell')
        trust_value = _derive_flow_value(row, 'trust_net', 'trust_buy', 'trust_sell')
        dealer_value = _derive_flow_value(row, 'dealer_net', 'dealer_buy', 'dealer_sell')

        if all(value is None for value in (foreign_value, trust_value, dealer_value)):
            continue

        trade_date = _format_trade_date(row.get('trade_date'))
        flow_rows = [
            {'label': '外資', 'value': _format_signed_number(foreign_value)},
            {'label': '投信', 'value': _format_signed_number(trust_value)},
            {'label': '自營商', 'value': _format_signed_number(dealer_value)},
        ]
        joined_values = ' / '.join(f"{item['label']} {item['value']}" for item in flow_rows)

        return {
            'trade_date': trade_date,
            'rows': flow_rows,
            'source': 'actual',
            'summary': f'{trade_date} 三大法人買賣超: {joined_values}' if trade_date else f'三大法人買賣超: {joined_values}',
            'note': f'資料來源: {table_name} 原始買賣超欄位',
            'is_fallback': False,
        }

    return None


def _get_news_translation_client():
    api_key = (os.getenv('GEMINI_API_KEY') or '').strip()
    if not api_key:
        return None

    try:
        from google import genai
    except ImportError:
        return None

    try:
        return genai.Client(api_key=api_key), genai
    except Exception as error:
        app.logger.warning('news translation unavailable: %s', error)
        return None


def _needs_chinese_translation(text_value):
    text_value = (text_value or '').strip()
    if not text_value:
        return False

    ascii_letters = sum(1 for char in text_value if char.isascii() and char.isalpha())
    cjk_chars = sum(1 for char in text_value if '\u4e00' <= char <= '\u9fff')
    return ascii_letters > cjk_chars


def _translate_news_items(items):
    if not items:
        return items

    client_bundle = _get_news_translation_client()
    translated_items = [dict(item) for item in items]
    if not client_bundle:
        return translated_items

    client, genai = client_bundle
    pending = []
    for index, item in enumerate(translated_items):
        fields = {}
        for field_name in ('title', 'summary'):
            original_value = (item.get(field_name) or '').strip()
            if not _needs_chinese_translation(original_value):
                continue

            cache_key = f'{field_name}:{original_value}'
            cached_value = _NEWS_TRANSLATION_CACHE.get(cache_key)
            if cached_value:
                item[field_name] = cached_value
                continue

            fields[field_name] = original_value

        if fields:
            pending.append({'index': index, **fields})

    if not pending:
        return translated_items

    prompt = (
        '請將以下美股新聞的標題與摘要翻譯成繁體中文。\n'
        '要求:\n'
        '1. 保留股票代碼、公司名、數字、百分比、季度與財報術語。\n'
        '2. 不要補充原文沒有的資訊。\n'
        '3. 只回傳 JSON 陣列，每個元素包含 index、title_zh、summary_zh。\n\n'
        f'輸入資料:\n{json.dumps(pending, ensure_ascii=False)}'
    )

    model_candidates = []
    for model_name in (NEWS_TRANSLATION_MODEL, NEWS_TRANSLATION_FALLBACK_MODEL):
        if model_name and model_name not in model_candidates:
            model_candidates.append(model_name)

    last_error = None
    for model_name in model_candidates:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=genai.types.GenerateContentConfig(
                    response_mime_type='application/json',
                ),
            )
            parsed = json.loads(response.text)
            if isinstance(parsed, dict):
                parsed = parsed.get('items', [])

            for translated in parsed if isinstance(parsed, list) else []:
                index = translated.get('index')
                if not isinstance(index, int) or index < 0 or index >= len(translated_items):
                    continue

                for field_name, translated_key in (('title', 'title_zh'), ('summary', 'summary_zh')):
                    translated_value = (translated.get(translated_key) or '').strip()
                    if not translated_value:
                        continue

                    original_value = (translated_items[index].get(field_name) or '').strip()
                    translated_items[index][field_name] = translated_value
                    _NEWS_TRANSLATION_CACHE[f'{field_name}:{original_value}'] = translated_value
            return translated_items
        except Exception as error:
            last_error = error

    try:
        from deep_translator import GoogleTranslator

        translator = GoogleTranslator(source='auto', target='zh-TW')
        for pending_item in pending:
            index = pending_item['index']
            for field_name in ('title', 'summary'):
                original_value = (pending_item.get(field_name) or '').strip()
                if not original_value:
                    continue

                translated_value = (translator.translate(original_value) or '').strip()
                if not translated_value:
                    continue

                translated_items[index][field_name] = translated_value
                _NEWS_TRANSLATION_CACHE[f'{field_name}:{original_value}'] = translated_value
        return translated_items
    except Exception as fallback_error:
        last_error = fallback_error if last_error is None else last_error

    if last_error is not None:
        app.logger.warning('news translation failed: %s', last_error)

    return translated_items


def _snapshot_backtest_job_state():
    with _backtest_job_lock:
        state = dict(_backtest_job_state)
        state['output_tail'] = list(_backtest_job_state.get('output_tail', []))
        return state


def _update_backtest_job_state(**updates):
    with _backtest_job_lock:
        _backtest_job_state.update(updates)


def _fetch_latest_backtest_run_metadata():
    try:
        with engine.connect() as conn:
            if not _table_exists(conn, 'backtest_runs'):
                return None, None

            row = conn.execute(text("""
                SELECT id, strategy_name
                FROM backtest_runs
                ORDER BY created_at DESC, id DESC
                LIMIT 1
            """)).mappings().first()
            if not row:
                return None, None
            return row['id'], row['strategy_name']
    except Exception as error:
        app.logger.warning('Unable to inspect latest backtest run: %s', error)
        return None, None


def _normalize_backtest_symbols(raw_symbols):
    if isinstance(raw_symbols, str):
        raw_symbols = raw_symbols.split(',')

    normalized = []
    seen = set()
    for value in raw_symbols or ():
        symbol = str(value or '').strip().upper()
        if not symbol or symbol in seen:
            continue
        normalized.append(symbol)
        seen.add(symbol)
    return normalized


def _coerce_backtest_request(payload):
    payload = payload if isinstance(payload, dict) else {}
    symbols = _normalize_backtest_symbols(payload.get('symbols')) or list(DEFAULT_ONECLICK_BACKTEST_SYMBOLS)
    if not symbols:
        raise ValueError('請至少提供一檔股票代碼')

    symbols = symbols[:MAX_FORM_BACKTEST_SYMBOLS]

    try:
        months = max(int(payload.get('months', DEFAULT_ONECLICK_BACKTEST_MONTHS)), 1)
    except (TypeError, ValueError):
        months = DEFAULT_ONECLICK_BACKTEST_MONTHS
    months = min(months, 36)

    try:
        top_n = max(int(payload.get('top_n', DEFAULT_ONECLICK_BACKTEST_TOP_N)), 1)
    except (TypeError, ValueError):
        top_n = DEFAULT_ONECLICK_BACKTEST_TOP_N
    top_n = min(top_n, len(symbols))

    pool_name = str(payload.get('pool_name') or 'custom').strip().lower()[:40] or 'custom'
    return {
        'symbols': symbols,
        'months': months,
        'top_n': top_n,
        'pool_name': pool_name,
    }


def _build_backtest_strategy_name(job_config):
    pool_name = str(job_config.get('pool_name') or 'custom').replace('-', ' ').replace('_', ' ').strip() or 'custom'
    return f"Dashboard {pool_name} {job_config['months']}M Top{job_config['top_n']}"


def _build_backtest_trade_rows(portfolio):
    open_positions = {}
    trade_rows = []

    for event in portfolio.trade_log:
        symbol = str(event.get('symbol') or '').upper()
        side = str(event.get('side') or '').upper()
        if not symbol or side not in {'BUY', 'SELL'}:
            continue

        if side == 'BUY':
            open_positions[symbol] = {
                'symbol': symbol,
                'entry_date': _format_trade_date(event.get('date')),
                'entry_price': _to_float(event.get('price')),
                'entry_notional': _to_float(event.get('notional')) or 0.0,
                'entry_friction': _to_float(event.get('friction')) or 0.0,
            }
            continue

        buy_event = open_positions.pop(symbol, None)
        if not buy_event:
            continue

        exit_notional = _to_float(event.get('notional')) or 0.0
        exit_friction = _to_float(event.get('friction')) or 0.0
        pnl = (exit_notional - exit_friction) - (buy_event['entry_notional'] + buy_event['entry_friction'])
        trade_rows.append({
            'symbol': symbol,
            'entry_date': buy_event['entry_date'],
            'exit_date': _format_trade_date(event.get('date')),
            'entry_price': buy_event['entry_price'],
            'exit_price': _to_float(event.get('price')),
            'pnl': pnl,
        })

    for open_event in open_positions.values():
        trade_rows.append({
            'symbol': open_event['symbol'],
            'entry_date': open_event['entry_date'],
            'exit_date': None,
            'entry_price': open_event['entry_price'],
            'exit_price': None,
            'pnl': None,
        })

    return trade_rows


def _persist_portfolio_backtest_run(job_config, start_date, end_date, equity_df, metrics, portfolio):
    strategy_name = _build_backtest_strategy_name(job_config)
    with engine.begin() as conn:
        result = conn.execute(text("""
            INSERT INTO backtest_runs (
                strategy_name, start_date, end_date, total_return, sharpe_ratio, max_drawdown
            ) VALUES (
                :strategy_name, :start_date, :end_date, :total_return, :sharpe_ratio, :max_drawdown
            )
        """), {
            'strategy_name': strategy_name,
            'start_date': start_date,
            'end_date': end_date,
            'total_return': float(metrics.get('total_return') or 0.0),
            'sharpe_ratio': float(metrics.get('sharpe') or 0.0),
            'max_drawdown': float(metrics.get('max_drawdown') or 0.0),
        })
        run_id = result.lastrowid

        if not equity_df.empty:
            equity_rows = [
                {
                    'run_id': run_id,
                    'date': _format_trade_date(row.date),
                    'equity_value': float(row.total_equity),
                }
                for row in equity_df[['date', 'total_equity']].itertuples(index=False)
            ]
            conn.execute(text("""
                INSERT INTO equity_curve (run_id, date, equity_value)
                VALUES (:run_id, :date, :equity_value)
            """), equity_rows)

        trade_rows = _build_backtest_trade_rows(portfolio)
        if trade_rows:
            conn.execute(text("""
                INSERT INTO trade_logs (
                    run_id, symbol, entry_date, exit_date, entry_price, exit_price, pnl
                ) VALUES (
                    :run_id, :symbol, :entry_date, :exit_date, :entry_price, :exit_price, :pnl
                )
            """), [{'run_id': run_id, **row} for row in trade_rows])

    return run_id, strategy_name


def _run_oneclick_backtest_job(job_config):
    import pandas as pd

    scripts_dir = PROJECT_ROOT / 'strategies' / 'scripts'
    scripts_dir_str = str(scripts_dir)
    if scripts_dir_str not in sys.path:
        sys.path.insert(0, scripts_dir_str)

    from run_portfolio_backtest import DEFAULT_INITIAL_CAPITAL, run_portfolio_backtest

    symbols = list(job_config['symbols'])
    months = int(job_config['months'])
    top_n = int(job_config['top_n'])
    request_summary = f"{len(symbols)} 檔 / {months} 個月 / Top {top_n}"

    _update_backtest_job_state(
        status='running',
        message=f'表單回測執行中（{request_summary}）',
        started_at=datetime.utcnow().isoformat(timespec='seconds'),
        finished_at=None,
        output_tail=[],
    )

    try:
        end_date = pd.Timestamp.today().normalize()
        start_date = end_date - pd.DateOffset(months=months)
        equity_df, metrics, portfolio = run_portfolio_backtest(
            symbols=symbols,
            start_date=start_date.strftime('%Y-%m-%d'),
            end_date=end_date.strftime('%Y-%m-%d'),
            initial_capital=float(DEFAULT_INITIAL_CAPITAL),
            top_n=top_n,
        )
        last_run_id, last_strategy_name = _persist_portfolio_backtest_run(
            job_config=job_config,
            start_date=start_date.strftime('%Y-%m-%d'),
            end_date=end_date.strftime('%Y-%m-%d'),
            equity_df=equity_df,
            metrics=metrics,
            portfolio=portfolio,
        )
        output_tail = [
            f"股票池: {', '.join(symbols[:8])}{' ...' if len(symbols) > 8 else ''}",
            f"期間: {start_date.strftime('%Y-%m-%d')} -> {end_date.strftime('%Y-%m-%d')}",
            f"總報酬: {metrics.get('total_return', 0.0):+.2%}",
            f"最大回撤: {metrics.get('max_drawdown', 0.0):+.2%}",
            f"夏普值: {metrics.get('sharpe', 0.0):.2f}",
        ]
        _update_backtest_job_state(
            status='completed',
            message=f'表單回測完成（{request_summary}）',
            finished_at=datetime.utcnow().isoformat(timespec='seconds'),
            last_run_id=last_run_id,
            last_strategy_name=last_strategy_name,
            output_tail=output_tail,
        )
    except Exception as error:
        app.logger.exception('Dashboard backtest failed: %s', error)
        _update_backtest_job_state(
            status='failed',
            message=f'表單回測執行失敗: {error}',
            finished_at=datetime.utcnow().isoformat(timespec='seconds'),
            output_tail=[str(error)],
        )


def _load_stock_snapshot(conn, symbol):
    row = conn.execute(text("""
        SELECT scan_date, symbol, signal_type, total_score, ml_confidence,
               current_price, support_1, support_2, resistance_1, resistance_2,
               breakout_pass, acceleration_pass, peg_pass, dupont_pass,
               institutional_pass, volume_structure_pass, money_flow_pass,
               multi_tf_momentum_pass, relative_strength_pass,
               earnings_quality_pass, sector_rotation_pass,
               pe_ratio, peg_ratio, pb_ratio, roe, insider_sentiment,
               sector, macro_regime, strategy_details, total_strategies
        FROM daily_recommendations
        WHERE symbol = :sym
        ORDER BY scan_date DESC
        LIMIT 1
    """), {'sym': symbol}).mappings().first()

    if not row:
        return None

    fundamentals = None
    if _table_exists(conn, 'stock_fundamentals'):
        fundamental_select = ',\n               '.join([
            _optional_column_expr(conn, 'stock_fundamentals', ['pe_ratio'], 'pe_ratio'),
            _optional_column_expr(conn, 'stock_fundamentals', ['peg_ratio'], 'peg_ratio'),
            _optional_column_expr(conn, 'stock_fundamentals', ['pb_ratio'], 'pb_ratio'),
            _optional_column_expr(conn, 'stock_fundamentals', ['market_cap'], 'market_cap'),
            _optional_column_expr(conn, 'stock_fundamentals', ['revenue_growth', 'revenue_growth_yoy'], 'revenue_growth'),
            _optional_column_expr(conn, 'stock_fundamentals', ['earnings_growth', 'earnings_growth_yoy'], 'earnings_growth'),
            _optional_column_expr(conn, 'stock_fundamentals', ['institutional_ownership', 'inst_ownership_pct'], 'institutional_ownership'),
            _optional_column_expr(conn, 'stock_fundamentals', ['insider_ownership_pct'], 'insider_ownership_pct'),
            _optional_column_expr(conn, 'stock_fundamentals', ['short_ratio'], 'short_ratio'),
            _optional_column_expr(conn, 'stock_fundamentals', ['gross_margin'], 'gross_margin'),
            _optional_column_expr(conn, 'stock_fundamentals', ['profit_margin'], 'profit_margin'),
            _optional_column_expr(conn, 'stock_fundamentals', ['free_cashflow'], 'free_cashflow'),
            _optional_column_expr(conn, 'stock_fundamentals', ['roe'], 'roe'),
            _optional_column_expr(conn, 'stock_fundamentals', ['sector'], 'sector'),
        ])

        fundamentals = conn.execute(text(f"""
            SELECT {fundamental_select}
            FROM stock_fundamentals
            WHERE symbol = :sym
            ORDER BY data_date DESC
            LIMIT 1
        """), {'sym': symbol}).mappings().first()

    strategy_details = None
    if row['strategy_details']:
        try:
            strategy_details = json.loads(row['strategy_details']) if isinstance(row['strategy_details'], str) else row['strategy_details']
        except Exception:
            strategy_details = None

    strategies = {
        'breakout': bool(row['breakout_pass']),
        'acceleration': bool(row['acceleration_pass']),
        'peg': bool(row['peg_pass']),
        'dupont': bool(row['dupont_pass']),
        'institutional': bool(row['institutional_pass']) if row['institutional_pass'] is not None else None,
        'volume_structure': bool(row['volume_structure_pass']) if row['volume_structure_pass'] is not None else None,
        'money_flow': bool(row['money_flow_pass']) if row['money_flow_pass'] is not None else None,
        'multi_tf_momentum': bool(row['multi_tf_momentum_pass']) if row['multi_tf_momentum_pass'] is not None else None,
        'relative_strength': bool(row['relative_strength_pass']) if row['relative_strength_pass'] is not None else None,
        'earnings_quality': bool(row['earnings_quality_pass']) if row['earnings_quality_pass'] is not None else None,
        'sector_rotation': bool(row['sector_rotation_pass']) if row['sector_rotation_pass'] is not None else None,
    }

    if fundamentals:
        fundamental_payload = {
            'pe_ratio': _to_float(fundamentals['pe_ratio']),
            'peg_ratio': _to_float(fundamentals['peg_ratio']),
            'pb_ratio': _to_float(fundamentals['pb_ratio']),
            'market_cap': _to_float(fundamentals['market_cap']),
            'revenue_growth': _to_float(fundamentals['revenue_growth']),
            'earnings_growth': _to_float(fundamentals['earnings_growth']),
            'institutional_ownership': _to_float(fundamentals['institutional_ownership']),
            'insider_ownership': _to_float(fundamentals['insider_ownership_pct']),
            'short_ratio': _to_float(fundamentals['short_ratio']),
            'gross_margin': _to_float(fundamentals['gross_margin']),
            'profit_margin': _to_float(fundamentals['profit_margin']),
            'free_cashflow': _to_float(fundamentals['free_cashflow']),
            'roe': _to_float(fundamentals['roe']),
            'sector': fundamentals['sector'],
        }
    else:
        fundamental_payload = {
            'pe_ratio': _to_float(row['pe_ratio']),
            'peg_ratio': _to_float(row['peg_ratio']),
            'pb_ratio': _to_float(row['pb_ratio']),
            'roe': _to_float(row['roe']),
            'sector': row['sector'],
        }

    return {
        'symbol': symbol,
        'scan_date': str(row['scan_date']),
        'signal': row['signal_type'],
        'total_score': _to_float(row['total_score']) or 0,
        'strategies': strategies,
        'fundamentals': fundamental_payload,
        'ml': {
            'confidence': _to_float(row['ml_confidence']),
        },
        'smart_money': {
            'insider_sentiment': row['insider_sentiment'] or 'NEUTRAL',
        },
        'price': {
            'current': _to_float(row['current_price']) or 0,
            'support_1': _to_float(row['support_1']),
            'support_2': _to_float(row['support_2']),
            'resistance_1': _to_float(row['resistance_1']),
            'resistance_2': _to_float(row['resistance_2']),
        },
        'macro_regime': row['macro_regime'],
        'total_strategies': int(row['total_strategies']) if row['total_strategies'] else 4,
        'strategy_details': strategy_details,
    }


def _load_recent_news(conn, symbol, limit=3):
    if not _table_exists(conn, 'news_cache'):
        return []

    rows = conn.execute(text("""
        SELECT date, title, summary, url, provider
        FROM news_cache
        WHERE symbol = :sym
        ORDER BY date DESC
        LIMIT :limit
    """), {'sym': symbol, 'limit': limit}).mappings()

    items = []
    for row in rows:
        items.append({
            'date': row['date'].strftime('%Y-%m-%d %H:%M:%S') if row['date'] else None,
            'title': row['title'],
            'summary': row['summary'],
            'url': row['url'],
            'provider': row['provider'],
        })
    return _translate_news_items(items)


def _normalize_chart_period(period):
    normalized = (period or 'd').strip().lower()
    return normalized if normalized in CHART_PERIOD_LABELS else 'd'


def _normalize_history_date(date_value):
    if date_value is None:
        return None, None

    if isinstance(date_value, datetime):
        date_obj = date_value.date()
    elif hasattr(date_value, 'strftime') and hasattr(date_value, 'year'):
        date_obj = date_value
    else:
        try:
            date_obj = datetime.strptime(str(date_value)[:10], '%Y-%m-%d').date()
        except ValueError:
            return None, None

    return date_obj, date_obj.strftime('%Y-%m-%d')


def _load_stock_history(conn, symbol, limit=420):
    if not _table_exists(conn, 'price_data_v2'):
        return []

    required_columns = ['date', 'open', 'high', 'low', 'close', 'volume']
    if any(not _column_exists(conn, 'price_data_v2', column) for column in required_columns):
        return []

    rows = conn.execute(text("""
        SELECT date, open, high, low, close, volume
        FROM (
            SELECT date, open, high, low, close, volume
            FROM price_data_v2
            WHERE symbol = :sym
            ORDER BY date DESC
            LIMIT :limit
        ) recent_history
        ORDER BY date ASC
    """), {'sym': symbol, 'limit': limit}).mappings()

    history = []
    for row in rows:
        date_obj, time_value = _normalize_history_date(row['date'])

        candle = {
            'date_obj': date_obj,
            'time': time_value,
            'open': _to_float(row['open']),
            'high': _to_float(row['high']),
            'low': _to_float(row['low']),
            'close': _to_float(row['close']),
            'volume': _to_float(row['volume']),
            'value': _to_float(row['close']) * _to_float(row['volume']) if row['close'] is not None and row['volume'] is not None else None,
        }
        if candle['date_obj'] and candle['time'] and None not in (candle['open'], candle['high'], candle['low'], candle['close'], candle['volume']):
            history.append(candle)

    return history


def _group_history_key(date_obj, period):
    if period == 'w':
        iso_year, iso_week, _ = date_obj.isocalendar()
        return f'{iso_year}-W{iso_week:02d}'
    return date_obj.strftime('%Y-%m')


def _compress_stock_history(history, period):
    period = _normalize_chart_period(period)
    if period == 'd':
        return history[-CHART_HISTORY_LIMITS['d']:]

    grouped = []
    current_key = None
    current = None

    for candle in history:
        group_key = _group_history_key(candle['date_obj'], period)
        if group_key != current_key:
            if current:
                grouped.append(current)
            current_key = group_key
            current = {
                'date_obj': candle['date_obj'],
                'time': candle['time'],
                'open': candle['open'],
                'high': candle['high'],
                'low': candle['low'],
                'close': candle['close'],
                'volume': candle['volume'],
                'value': candle['value'] or 0,
            }
            continue

        current['date_obj'] = candle['date_obj']
        current['time'] = candle['time']
        current['high'] = max(current['high'], candle['high'])
        current['low'] = min(current['low'], candle['low'])
        current['close'] = candle['close']
        current['volume'] += candle['volume']
        current['value'] += candle['value'] or 0

    if current:
        grouped.append(current)

    return grouped[-CHART_HISTORY_LIMITS[period]:]


def _trim_candles_for_response(candles):
    trimmed = []
    for candle in candles:
        trimmed.append({
            'time': candle['time'],
            'open': candle['open'],
            'high': candle['high'],
            'low': candle['low'],
            'close': candle['close'],
            'volume': candle['volume'],
            'value': candle['value'],
        })
    return trimmed


def _build_sma_series(candles, window):
    if len(candles) < window:
        return []

    series = []
    rolling_sum = 0.0
    closes = [candle['close'] for candle in candles]
    for index, close_value in enumerate(closes):
        rolling_sum += close_value
        if index >= window:
            rolling_sum -= closes[index - window]
        if index + 1 >= window:
            series.append({
                'time': candles[index]['time'],
                'value': rolling_sum / window,
            })
    return series


def _build_ema_values(values, period):
    if not values:
        return []

    multiplier = 2 / (period + 1)
    ema_values = []
    current = None
    for value in values:
        current = value if current is None else ((value - current) * multiplier) + current
        ema_values.append(current)
    return ema_values


def _build_macd_payload(candles):
    closes = [candle['close'] for candle in candles]
    if len(closes) < 26:
        return {
            'macd': [],
            'signal': [],
            'histogram': [],
            'empty_message': 'K 線資料不足，暫時無法計算 MACD',
        }

    macd_values = []
    fast_ema = _build_ema_values(closes, 12)
    slow_ema = _build_ema_values(closes, 26)
    for fast_value, slow_value in zip(fast_ema, slow_ema):
        macd_values.append(fast_value - slow_value)

    signal_values = _build_ema_values(macd_values, 9)
    histogram_values = [macd - signal for macd, signal in zip(macd_values, signal_values)]

    return {
        'macd': [
            {'time': candle['time'], 'value': value}
            for candle, value in zip(candles, macd_values)
        ],
        'signal': [
            {'time': candle['time'], 'value': value}
            for candle, value in zip(candles, signal_values)
        ],
        'histogram': [
            {
                'time': candle['time'],
                'value': value,
                'color': 'rgba(46, 160, 67, 0.65)' if value >= 0 else 'rgba(248, 81, 73, 0.65)',
            }
            for candle, value in zip(candles, histogram_values)
        ],
        'empty_message': None,
    }


def _build_rsi_payload(candles, period=14):
    closes = [candle['close'] for candle in candles]
    if len(closes) <= period:
        return {
            'series': [],
            'bands': [30, 70],
            'empty_message': 'K 線資料不足，暫時無法計算 RSI',
        }

    series = []
    for index in range(period, len(closes)):
        window = closes[index - period:index + 1]
        gains = 0.0
        losses = 0.0
        for previous, current in zip(window, window[1:]):
            delta = current - previous
            if delta >= 0:
                gains += delta
            else:
                losses -= delta

        avg_gain = gains / period
        avg_loss = losses / period
        if avg_loss == 0:
            value = 100.0 if avg_gain > 0 else 50.0
        else:
            rs = avg_gain / avg_loss
            value = 100 - (100 / (1 + rs))
        series.append({'time': candles[index]['time'], 'value': value})

    return {
        'series': series,
        'bands': [30, 70],
        'empty_message': None,
    }


def _build_kd_payload(candles, period=9):
    if len(candles) < period:
        return {
            'k': [],
            'd': [],
            'j': [],
            'bands': [20, 80],
            'empty_message': 'K 線資料不足，暫時無法計算 KD',
        }

    k_series = []
    d_series = []
    j_series = []
    previous_k = None
    previous_d = None

    for index in range(period - 1, len(candles)):
        window = candles[index - period + 1:index + 1]
        low_value = min(item['low'] for item in window)
        high_value = max(item['high'] for item in window)
        if high_value == low_value:
            rsv = 50.0
        else:
            rsv = ((candles[index]['close'] - low_value) / (high_value - low_value)) * 100

        current_k = rsv if previous_k is None else ((2 * previous_k) + rsv) / 3
        current_d = current_k if previous_d is None else ((2 * previous_d) + current_k) / 3
        current_j = (3 * current_k) - (2 * current_d)

        previous_k = current_k
        previous_d = current_d
        k_series.append({'time': candles[index]['time'], 'value': current_k})
        d_series.append({'time': candles[index]['time'], 'value': current_d})
        j_series.append({'time': candles[index]['time'], 'value': current_j})

    return {
        'k': k_series,
        'd': d_series,
        'j': j_series,
        'bands': [20, 80],
        'empty_message': None,
    }


def _build_flow_payload(candles):
    if not candles:
        return {
            'label': '量價資金代理',
            'source': 'proxy',
            'kind': 'histogram',
            'series': [],
            'trend': [],
            'empty_message': '目前無可用量價資料，暫不顯示 flow pane',
        }

    series = []
    signed_values = []
    for candle in candles:
        direction = 1 if candle['close'] > candle['open'] else -1 if candle['close'] < candle['open'] else 0
        signed_value = (candle['close'] * candle['volume']) * direction
        signed_values.append(signed_value)
        series.append({
            'time': candle['time'],
            'value': signed_value,
            'color': 'rgba(46, 160, 67, 0.65)' if signed_value >= 0 else 'rgba(248, 81, 73, 0.65)',
        })

    trend_values = _build_ema_values(signed_values, 5)
    trend = [
        {'time': candle['time'], 'value': value}
        for candle, value in zip(candles, trend_values)
    ]

    return {
        'label': '量價資金代理',
        'source': 'proxy',
        'kind': 'histogram',
        'series': series,
        'trend': trend,
        'empty_message': None,
    }


def _build_chart_price_lines(stock):
    if not stock:
        return []

    return [
        line for line in [
            {'key': 'support_1', 'title': 'S1', 'price': stock['price'].get('support_1'), 'color': '#2ea043'},
            {'key': 'support_2', 'title': 'S2', 'price': stock['price'].get('support_2'), 'color': 'rgba(46, 160, 67, 0.75)'},
            {'key': 'resistance_1', 'title': 'R1', 'price': stock['price'].get('resistance_1'), 'color': '#f85149'},
            {'key': 'resistance_2', 'title': 'R2', 'price': stock['price'].get('resistance_2'), 'color': 'rgba(248, 81, 73, 0.75)'},
        ]
        if line['price'] is not None
    ]


def _build_history_bundle(conn, symbol, period='d'):
    normalized_period = _normalize_chart_period(period)
    raw_history = _load_stock_history(conn, symbol, limit=CHART_FETCH_LIMITS[normalized_period])
    candles = _compress_stock_history(raw_history, normalized_period)
    stock = _load_stock_snapshot(conn, symbol)

    price_lines = _build_chart_price_lines(stock)
    ma5 = _build_sma_series(candles, 5)
    ma20 = _build_sma_series(candles, 20)
    ma60 = _build_sma_series(candles, 60)
    macd = _build_macd_payload(candles)
    rsi = _build_rsi_payload(candles)
    kd = _build_kd_payload(candles)
    flow = _build_flow_payload(candles)

    return {
        'symbol': symbol,
        'period': normalized_period,
        'period_label': CHART_PERIOD_LABELS[normalized_period],
        'candles': _trim_candles_for_response(candles),
        'meta': {
            'candle_count': len(candles),
            'history_limit': CHART_HISTORY_LIMITS[normalized_period],
            'flow_source': flow['source'],
            'supports_resistances_available': bool(price_lines),
        },
        'overlays': {
            'moving_averages': {
                'ma5': ma5,
                'ma20': ma20,
                'ma60': ma60,
            },
            'price_lines': price_lines,
        },
        'indicators': {
            'macd': macd,
            'rsi': rsi,
            'kd': kd,
        },
        'flow': flow,
        'empty_message': None if candles else f'{symbol} 目前無可用的 {CHART_PERIOD_LABELS[normalized_period]} OHLCV 資料',
    }


def _strategy_label(strategy_name):
    labels = {
        'breakout': '突破',
        'acceleration': '加速',
        'peg': 'PEG',
        'dupont': '杜邦',
        'institutional': '法人籌碼',
        'volume_structure': '量價結構',
        'money_flow': '資金流',
        'multi_tf_momentum': '多週期動能',
        'relative_strength': '相對強勢',
        'earnings_quality': '盈餘品質',
        'sector_rotation': '產業輪動',
    }
    return labels.get(strategy_name, strategy_name)


def _build_diagnostics(stock):
    positive = []
    caution = []
    neutral = []

    for name, passed in stock['strategies'].items():
        label = _strategy_label(name)
        if passed is True:
            positive.append(f'{label}條件成立')
        elif passed is False:
            caution.append(f'{label}條件未通過')

    confidence = stock['ml']['confidence']
    if confidence is not None:
        if confidence >= 0.75:
            positive.append(f'AI 信心偏強 ({confidence * 100:.0f}%)')
        elif confidence <= 0.4:
            caution.append(f'AI 信心偏弱 ({confidence * 100:.0f}%)')
        else:
            neutral.append(f'AI 信心中性 ({confidence * 100:.0f}%)')

    regime = stock.get('macro_regime')
    if regime:
        if regime == 'RISK_ON':
            positive.append('總經環境偏向風險承擔')
        elif regime == 'RISK_OFF':
            caution.append('總經環境偏保守，追價需控制部位')
        else:
            neutral.append(f'總經環境為 {regime}')

    fundamentals = stock['fundamentals']
    if fundamentals.get('institutional_ownership') is not None:
        ownership = fundamentals['institutional_ownership']
        if ownership >= 0.6:
            positive.append(f'機構持股比例偏高 ({ownership * 100:.1f}%)')
        elif ownership <= 0.25:
            caution.append(f'機構持股比例偏低 ({ownership * 100:.1f}%)')

    if fundamentals.get('revenue_growth') is not None:
        growth = fundamentals['revenue_growth']
        if growth > 0:
            positive.append(f'營收成長為正 ({growth * 100:.1f}%)')
        else:
            caution.append(f'營收成長為負 ({growth * 100:.1f}%)')

    if not neutral:
        neutral.append('目前以既有量化欄位組合診斷，尚未接入獨立 LLM 摘要流程')

    return {
        'positive': positive[:4],
        'caution': caution[:4],
        'neutral': neutral[:3],
    }


def _build_flow_context(stock):
    items = []
    strategies = stock['strategies']
    fundamentals = stock['fundamentals']
    smart_money = stock.get('smart_money', {})
    insider_sentiment = (smart_money.get('insider_sentiment') or 'NEUTRAL').upper()

    if strategies.get('institutional') is True and strategies.get('money_flow') is True:
        trend_label = '法人大戶動向偏多，疑似持續吸籌'
    elif strategies.get('institutional') is True:
        trend_label = '法人大戶持股偏強，但短線流向尚待確認'
    elif strategies.get('money_flow') is True:
        trend_label = '短線資金回流，但法人大戶態度仍需觀察'
    elif strategies.get('institutional') is False:
        trend_label = '法人大戶動向偏保守，暫未看到明確加碼'
    else:
        trend_label = '法人大戶動向資料有限，先以量價代理觀察'

    items.append(trend_label)

    if insider_sentiment == 'BUYING':
        items.append('內部人近期偏買方，與主力方向較一致')
    elif insider_sentiment == 'SELLING':
        items.append('內部人近期偏賣方，需留意主力一致性')

    if strategies.get('institutional') is True:
        items.append('法人籌碼策略通過，主力動向偏多')
    elif strategies.get('institutional') is False:
        items.append('法人籌碼策略未過關，追價前需再觀察')

    if strategies.get('money_flow') is True:
        items.append('資金流訊號偏正向')
    elif strategies.get('money_flow') is False:
        items.append('資金流訊號未確認')

    if fundamentals.get('institutional_ownership') is not None:
        items.append(f"機構持股約 {fundamentals['institutional_ownership'] * 100:.1f}%")

    if not items:
        items.append('法人籌碼資料不足，先以價格結構與策略訊號觀察')

    return {
        'title': '法人與籌碼觀察',
        'items': items,
        'trend_label': trend_label,
        'is_fallback': items == ['法人籌碼資料不足，先以價格結構與策略訊號觀察'],
    }


def _format_money_compact(value):
    numeric = _to_float(value)
    if numeric is None:
        return None

    abs_value = abs(numeric)
    if abs_value >= 1_000_000_000:
        return f'${numeric / 1_000_000_000:.2f}B'
    if abs_value >= 1_000_000:
        return f'${numeric / 1_000_000:.2f}M'
    if abs_value >= 1_000:
        return f'${numeric / 1_000:.2f}K'
    return f'${numeric:.2f}'


def _build_today_flow_snapshot(conn, symbol, stock=None):
    actual_snapshot = _load_actual_institutional_flow_snapshot(conn, symbol)
    if actual_snapshot:
        return actual_snapshot

    return {
        'trade_date': None,
        'date_label': '快照日期',
        'headline_label': '法人 / 內部人快照',
        'rows': [
            {'label': '機構持股', 'value': '待更新'},
            {'label': '共同基金', 'value': '待更新'},
            {'label': '內部人近6M', 'value': '待更新'},
        ],
        'source': 'unavailable',
        'summary': '尚未建立美股機構 / 共同基金 / 內部人快照資料',
        'note': '請先執行機構籌碼 ingestion，寫入 us_institutional_activity 後即可顯示真實數值。',
        'is_fallback': True,
    }


def _build_playbooks(stock):
    current_price = stock['price']['current'] or 0
    support_1 = stock['price']['support_1']
    support_2 = stock['price']['support_2']
    resistance_1 = stock['price']['resistance_1']
    resistance_2 = stock['price']['resistance_2']

    def zone(low, high):
        if low is None and high is None:
            return '待更多價格資料'
        if low is None:
            return f'約 ${high:.2f}'
        if high is None:
            return f'約 ${low:.2f}'
        if abs(low - high) < 0.01:
            return f'${low:.2f}'
        return f'${low:.2f} - ${high:.2f}'

    breakout_entry_low = current_price if current_price else resistance_1
    breakout_entry_high = resistance_1 or current_price
    pullback_low = support_1 or support_2
    pullback_high = current_price if current_price else support_1
    defensive_low = support_2 or support_1
    defensive_high = support_1 or current_price

    return [
        {
            'key': 'breakout',
            'title': '開高走高劇本',
            'tone': 'positive',
            'entry_zone': zone(breakout_entry_low, breakout_entry_high),
            'stop_loss': zone(support_1, support_1),
            'targets': [zone(resistance_1, resistance_2), zone(resistance_2, resistance_2)],
            'summary': '適合突破後延續追蹤，重點看壓力轉支撐是否成立。',
        },
        {
            'key': 'pullback',
            'title': '震盪整理劇本',
            'tone': 'neutral',
            'entry_zone': zone(pullback_low, pullback_high),
            'stop_loss': zone(support_2, support_2),
            'targets': [zone(current_price, resistance_1), zone(resistance_1, resistance_2)],
            'summary': '適合等待回踩承接，優先觀察支撐區是否有守。',
        },
        {
            'key': 'defensive',
            'title': '開低回測劇本',
            'tone': 'negative',
            'entry_zone': zone(defensive_low, defensive_high),
            'stop_loss': zone(support_2, support_2),
            'targets': [zone(current_price, current_price), zone(support_1, current_price)],
            'summary': '若跌破關鍵支撐，轉為防守觀察或等待結構重新站穩。',
        },
    ]


def _build_war_room_payload(stock, news_items, today_flow):
    diagnostics = _build_diagnostics(stock)
    fundamentals = stock['fundamentals']
    flow_context = _build_flow_context(stock)
    if today_flow and today_flow.get('summary'):
        flow_context['items'].append(today_flow['summary'])
        if today_flow.get('note'):
            flow_context['items'].append(today_flow['note'])

    return {
        'symbol': stock['symbol'],
        'overview': {
            'symbol': stock['symbol'],
            'signal': stock['signal'],
            'total_score': stock['total_score'],
            'confidence': stock['ml']['confidence'],
            'scan_date': stock['scan_date'],
            'macro_regime': stock.get('macro_regime'),
            'sector': fundamentals.get('sector'),
        },
        'price_map': stock['price'],
        'strategies': stock['strategies'],
        'fundamentals': fundamentals,
        'diagnostics': diagnostics,
        'summary_sections': [
            {
                'title': '趨勢分析',
                'tone': 'positive',
                'lines': diagnostics['positive'][:2] or ['目前趨勢訊號不足，先觀察價格結構。'],
            },
            {
                'title': '籌碼追蹤',
                'tone': 'highlight',
                'lines': flow_context['items'][:2],
            },
            {
                'title': '總經與產業連動',
                'tone': 'neutral',
                'lines': diagnostics['neutral'][:2] or ['目前無額外總經與產業補充。'],
            },
        ],
        'flow_context': flow_context,
        'today_flow': today_flow,
        'news': {
            'items': news_items,
            'empty_message': '目前無最新消息',
        },
        'playbooks': _build_playbooks(stock),
        'chart': {
            'symbol': stock['symbol'],
            'status': 'placeholder',
            'message': '此區預留給 TradingView Lightweight Charts 渲染 K 線與籌碼圖表',
        },
        'strategy_details': stock['strategy_details'],
    }


@app.route('/api/stock/<symbol>')
@auth.login_required
def get_stock_detail(symbol):
    """
    取得個股完整分析（11 策略 + 基本面 + ML 信心度）

    Returns:
        JSON: {symbol, scan_date, strategies:{...}, fundamentals:{...}, ml:{...}, price:{...}}
    """
    symbol = symbol.upper()
    try:
        with engine.connect() as conn:
            stock = _load_stock_snapshot(conn, symbol)
            if not stock:
                return jsonify({'error': f'{symbol} 無推薦資料'}), 404
            return jsonify(stock)

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/stock/<symbol>/war-room')
@auth.login_required
def get_stock_war_room(symbol):
    """取得戰情室使用的單一個股整合觀察資料。"""
    symbol = symbol.upper()
    try:
        with engine.connect() as conn:
            stock = _load_stock_snapshot(conn, symbol)
            if not stock:
                return jsonify({'error': f'{symbol} 無推薦資料'}), 404

            news_items = _load_recent_news(conn, symbol)
            today_flow = _build_today_flow_snapshot(conn, symbol, stock=stock)
            return jsonify(_build_war_room_payload(stock, news_items, today_flow))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/stock/<symbol>/history')
@auth.login_required
def get_stock_history(symbol):
    """取得戰情室圖表使用的 period-aware 歷史資料 bundle。"""
    symbol = symbol.upper()
    period = request.args.get('period', 'd')
    try:
        with engine.connect() as conn:
            return jsonify(_build_history_bundle(conn, symbol, period=period))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/backtest/status')
@auth.login_required
def get_backtest_status():
    """回傳一鍵回測目前執行狀態。"""
    return jsonify(_snapshot_backtest_job_state())


@app.route('/api/backtest/run', methods=['POST'])
@auth.login_required
def run_backtest_once():
    """以表單參數觸發一次後台回測。"""
    try:
        job_config = _coerce_backtest_request(request.get_json(silent=True) or {})
    except ValueError as error:
        return jsonify({'error': str(error)}), 400

    with _backtest_job_lock:
        if _backtest_job_state.get('status') == 'running':
            state = dict(_backtest_job_state)
            state['output_tail'] = list(_backtest_job_state.get('output_tail', []))
            return jsonify(state), 409

        _backtest_job_state.update({
            'status': 'queued',
            'message': f"表單回測已排入執行（{len(job_config['symbols'])} 檔 / {job_config['months']} 個月 / Top {job_config['top_n']}）",
            'started_at': datetime.utcnow().isoformat(timespec='seconds'),
            'finished_at': None,
            'last_run_id': _backtest_job_state.get('last_run_id'),
            'last_strategy_name': _backtest_job_state.get('last_strategy_name'),
            'output_tail': [],
        })

    worker = threading.Thread(target=_run_oneclick_backtest_job, args=(job_config,), daemon=True)
    worker.start()
    return jsonify(_snapshot_backtest_job_state()), 202


# ============================================
# 持倉 API
# ============================================
@app.route('/api/portfolio')
@auth.login_required
def get_portfolio():
    """
    取得最新回測/策略的持倉（尚未出場的交易）

    Returns:
        JSON: {holdings:[...], summary:{cash, equity, positions_value}}
    """
    empty_payload = {'holdings': []}

    try:
        with engine.connect() as conn:
            if not _table_exists(conn, 'trade_logs'):
                return jsonify(empty_payload)

            has_confidence = _column_exists(conn, 'trade_logs', 'confidence')
            conf_expr = 't.confidence' if has_confidence else 'NULL AS confidence'

            # 尚未出場的持倉
            strategy_expr = 'r.strategy_name' if _table_exists(conn, 'backtest_runs') else 'NULL AS strategy_name'
            join_clause = 'LEFT JOIN backtest_runs r ON t.run_id = r.id' if _table_exists(conn, 'backtest_runs') else ''
            rows = conn.execute(text(f"""
                SELECT t.symbol, t.entry_date, t.entry_price, {conf_expr},
                       {strategy_expr}
                FROM trade_logs t
                {join_clause}
                WHERE t.exit_date IS NULL
                ORDER BY t.entry_date DESC
            """))

            holdings = []
            for row in rows:
                holdings.append({
                    'symbol':      row[0],
                    'entry_date':  str(row[1]) if row[1] else None,
                    'entry_price': float(row[2]) if row[2] else 0,
                    'confidence':  float(row[3]) if row[3] else None,
                    'strategy':    row[4],
                })

            # 如無持倉，改取最近一次回測結束時仍在場的交易
            if not holdings:
                latest_run = conn.execute(text(
                    "SELECT id FROM backtest_runs ORDER BY created_at DESC LIMIT 1"
                )).scalar()
                if latest_run:
                    conf_expr2 = 'confidence' if has_confidence else 'NULL AS confidence'
                    rows2 = conn.execute(text(f"""
                        SELECT symbol, entry_date, entry_price, exit_date, exit_price, pnl, {conf_expr2}
                        FROM trade_logs
                        WHERE run_id = :rid
                        ORDER BY entry_date DESC
                        LIMIT 20
                    """), {'rid': latest_run})
                    for row in rows2:
                        holdings.append({
                            'symbol':      row[0],
                            'entry_date':  str(row[1]) if row[1] else None,
                            'entry_price': float(row[2]) if row[2] else 0,
                            'exit_date':   str(row[3]) if row[3] else None,
                            'exit_price':  float(row[4]) if row[4] else 0,
                            'pnl':         float(row[5]) if row[5] else 0,
                            'confidence':  float(row[6]) if row[6] else None,
                        })

            return jsonify({'holdings': holdings})

    except Exception as e:
        return _handle_dashboard_exception('portfolio', empty_payload, e)


# ============================================
# 宏觀指標 API
# ============================================
@app.route('/api/portfolio/state')
@auth.login_required
def get_portfolio_state():
    empty_payload = {
        'holdings': [],
        'summary': {},
        'sector_breakdown': [],
        'correlation': _build_empty_correlation_payload(),
        'source': 'open_positions',
    }

    try:
        from analytics.correlation_engine import build_correlation_payload, build_sector_breakdown

        with engine.connect() as conn:
            holdings = _load_portfolio_state_holdings(conn)
            if not holdings:
                return jsonify({
                    'holdings': [],
                    'summary': {'positions': 0, 'distinct_sectors': 0},
                    'sector_breakdown': [],
                    'correlation': _build_empty_correlation_payload('目前沒有未平倉持倉'),
                    'source': 'open_positions',
                })

        price_history = _load_price_history_for_symbols([holding['symbol'] for holding in holdings])
        sector_breakdown = build_sector_breakdown(holdings)
        correlation = build_correlation_payload(
            [holding['symbol'] for holding in holdings],
            price_history,
            window_days=60,
        )
        summary = {
            'positions': len(holdings),
            'distinct_sectors': len(sector_breakdown),
            'symbols': [holding['symbol'] for holding in holdings],
        }
        return jsonify({
            'holdings': holdings,
            'summary': summary,
            'sector_breakdown': sector_breakdown,
            'correlation': correlation,
            'source': 'open_positions',
        })

    except Exception as e:
        return _handle_dashboard_exception('portfolio_state', empty_payload, e)


@app.route('/api/universe/sync-status')
@auth.login_required
def get_universe_sync_status():
    empty_payload = {
        'universe_code': None,
        'status': 'unavailable',
        'processed_symbols': 0,
        'total_symbols': 0,
        'progress_pct': 0.0,
        'finished_at': None,
        'error_message': None,
    }

    try:
        with engine.connect() as conn:
            return jsonify(_build_universe_sync_payload(conn))
    except Exception as e:
        return _handle_dashboard_exception('universe_sync_status', empty_payload, e)


@app.route('/api/macro')
@auth.login_required
def get_macro():
    """
    取得宏觀經濟指標 + 最新 Regime

    Returns:
        JSON: {regime:{...}, indicators:{vix, yield_curve, unemployment, fed_rate, cpi}}
    """
    empty_payload = {'regime': None, 'indicators': {}}

    try:
        with engine.connect() as conn:
            # 最新 Regime
            regime_row = None
            if _table_exists(conn, 'macro_regime_log'):
                regime_row = conn.execute(text("""
                    SELECT regime, vix, yield_curve, unemployment_rate, fed_rate, description, report_date
                    FROM macro_regime_log
                    ORDER BY report_date DESC
                    LIMIT 1
                """)).first()

            regime = None
            if regime_row:
                regime = {
                    'regime':           regime_row[0],
                    'vix':              float(regime_row[1]) if regime_row[1] else None,
                    'yield_curve':      float(regime_row[2]) if regime_row[2] else None,
                    'unemployment_rate':float(regime_row[3]) if regime_row[3] else None,
                    'fed_rate':         float(regime_row[4]) if regime_row[4] else None,
                    'description':      regime_row[5],
                    'report_date':      str(regime_row[6]),
                }

            # 最新各指標（從 macro_data）
            indicators = {}
            ticker_map = {
                'VIXCLS':   'vix',
                'T10Y2Y':   'yield_curve',
                'UNRATE':   'unemployment_rate',
                'DFF':      'fed_rate',
                'CPIAUCSL': 'cpi',
            }
            if _table_exists(conn, 'macro_data'):
                if _column_exists(conn, 'macro_data', 'ticker'):
                    code_col = 'ticker'
                elif _column_exists(conn, 'macro_data', 'indicator'):
                    code_col = 'indicator'
                else:
                    code_col = None

                code_alias_map = {
                    'VIXCLS': ['VIXCLS', 'VIX'],
                    'T10Y2Y': ['T10Y2Y'],
                    'UNRATE': ['UNRATE'],
                    'DFF': ['DFF'],
                    'CPIAUCSL': ['CPIAUCSL', 'CPI'],
                }

                if code_col:
                    for fred_code, key in ticker_map.items():
                        val_row = None
                        for candidate in code_alias_map.get(fred_code, [fred_code]):
                            val_row = conn.execute(text(f"""
                                SELECT value, date FROM macro_data
                                WHERE {code_col} = :t
                                ORDER BY date DESC LIMIT 1
                            """), {'t': candidate}).first()
                            if val_row:
                                break
                        if val_row:
                            indicators[key] = {
                                'value': float(val_row[0]) if val_row[0] else None,
                                'date':  str(val_row[1]),
                            }

            if regime is None and indicators:
                yield_curve_val = indicators.get('yield_curve', {}).get('value')
                fed_rate_val = indicators.get('fed_rate', {}).get('value')

                derived_regime = 'NEUTRAL'
                derived_desc = 'Derived from macro_data fallback'
                if yield_curve_val is not None and yield_curve_val < 0:
                    derived_regime = 'RISK_OFF'
                    derived_desc = 'Fallback: inverted yield curve suggests defensive mode'
                elif yield_curve_val is not None and yield_curve_val > 0.3 and (fed_rate_val is None or fed_rate_val < 5.0):
                    derived_regime = 'RISK_ON'
                    derived_desc = 'Fallback: positive curve and moderate rates suggest risk-on'

                report_dates = [v.get('date') for v in indicators.values() if isinstance(v, dict) and v.get('date')]
                regime = {
                    'regime': derived_regime,
                    'vix': indicators.get('vix', {}).get('value'),
                    'yield_curve': indicators.get('yield_curve', {}).get('value'),
                    'unemployment_rate': indicators.get('unemployment_rate', {}).get('value'),
                    'fed_rate': indicators.get('fed_rate', {}).get('value'),
                    'description': derived_desc,
                    'report_date': max(report_dates) if report_dates else None,
                }

            return jsonify({
                'regime': regime,
                'indicators': indicators,
            })

    except Exception as e:
        return _handle_dashboard_exception('macro', empty_payload, e)


# ============================================
# 產業動能 API
# ============================================
@app.route('/api/sectors')
@auth.login_required
def get_sectors():
    """
    取得產業動能排行

    Returns:
        JSON: {report_date, sectors:[{sector, etf, return_20d, return_63d, return_252d, rank}]}
    """
    empty_payload = {'report_date': None, 'sectors': []}

    try:
        with engine.connect() as conn:
            if _table_exists(conn, 'sector_momentum'):
                latest = conn.execute(text(
                    "SELECT MAX(report_date) FROM sector_momentum"
                )).scalar()

                if latest:
                    etf_col = 'etf_symbol' if _column_exists(conn, 'sector_momentum', 'etf_symbol') else 'etf'
                    rows = conn.execute(text(f"""
                        SELECT sector, {etf_col}, return_20d, return_63d, return_252d, rank_position
                        FROM sector_momentum
                        WHERE report_date = :d
                        ORDER BY rank_position ASC
                    """), {'d': str(latest)})

                    sectors = []
                    for row in rows:
                        sectors.append({
                            'sector':      row[0],
                            'etf':         row[1],
                            'return_20d':  float(row[2]) if row[2] else None,
                            'return_63d':  float(row[3]) if row[3] else None,
                            'return_252d': float(row[4]) if row[4] else None,
                            'rank':        row[5],
                        })

                    return jsonify({'report_date': str(latest), 'sectors': sectors})

            # Fallback: 若無 sector_momentum，使用最新推薦聚合
            if not _table_exists(conn, 'daily_recommendations'):
                return jsonify({'report_date': None, 'sectors': []})

            latest_scan = conn.execute(text("SELECT MAX(scan_date) FROM daily_recommendations")).scalar()
            if not latest_scan:
                return jsonify({'report_date': None, 'sectors': []})

            sectors = []
            if _column_exists(conn, 'daily_recommendations', 'sector'):
                rows = conn.execute(text("""
                    SELECT COALESCE(sector, 'Unknown') AS sector_name,
                           COUNT(*) AS stock_count,
                           AVG(total_score) AS avg_score
                    FROM daily_recommendations
                    WHERE scan_date = :d
                    GROUP BY COALESCE(sector, 'Unknown')
                    ORDER BY avg_score DESC, stock_count DESC
                """), {'d': str(latest_scan)})

                rank = 1
                for row in rows:
                    sectors.append({
                        'sector': row[0],
                        'etf': None,
                        'return_20d': None,
                        'return_63d': None,
                        'return_252d': None,
                        'rank': rank,
                        'stock_count': int(row[1]) if row[1] else 0,
                        'avg_score': float(row[2]) if row[2] else None,
                    })
                    rank += 1
            else:
                rows = conn.execute(text("""
                    SELECT symbol, total_score
                    FROM daily_recommendations
                    WHERE scan_date = :d
                """), {'d': str(latest_scan)})
                from constants import SECTOR_MAP_FALLBACK
                sector_map = SECTOR_MAP_FALLBACK
                agg = {}
                for row in rows:
                    sym = row[0]
                    score = float(row[1]) if row[1] else 0.0
                    sector_name = sector_map.get(sym, 'Other')
                    if sector_name not in agg:
                        agg[sector_name] = {'count': 0, 'score_sum': 0.0}
                    agg[sector_name]['count'] += 1
                    agg[sector_name]['score_sum'] += score

                sorted_items = sorted(
                    agg.items(),
                    key=lambda item: (item[1]['score_sum'] / max(item[1]['count'], 1), item[1]['count']),
                    reverse=True,
                )
                for idx, (sector_name, stats) in enumerate(sorted_items, start=1):
                    sectors.append({
                        'sector': sector_name,
                        'etf': None,
                        'return_20d': None,
                        'return_63d': None,
                        'return_252d': None,
                        'rank': idx,
                        'stock_count': stats['count'],
                        'avg_score': round(stats['score_sum'] / max(stats['count'], 1), 4),
                    })

            return jsonify({'report_date': str(latest_scan), 'sectors': sectors, 'source': 'daily_recommendations_fallback'})

    except Exception as e:
        return _handle_dashboard_exception('sectors', empty_payload, e)


# ============================================
# 推薦日期列表 API
# ============================================
@app.route('/api/recommendations/dates')
@auth.login_required
def get_recommendation_dates():
    """取得所有有推薦資料的日期列表"""
    empty_payload = {'dates': []}

    try:
        with engine.connect() as conn:
            if not _table_exists(conn, 'daily_recommendations'):
                return jsonify(empty_payload)

            rows = conn.execute(text(
                "SELECT DISTINCT scan_date FROM daily_recommendations ORDER BY scan_date DESC LIMIT 60"
            ))
            dates = [str(row[0]) for row in rows]
            return jsonify({'dates': dates})
    except Exception as e:
        return _handle_dashboard_exception('recommendation_dates', empty_payload, e)


if __name__ == '__main__':
    port = int(os.getenv('WEB_PORT', '5000'))
    print("🚀 啟動 Flask 儀表板...")
    print(f"   DB: {DB_CONFIG['host']}:{DB_CONFIG['port']}:{DB_CONFIG['name']}")
    print(f"   訪問地址: http://127.0.0.1:{port}")
    print(f"   對外監聽: http://0.0.0.0:{port}")
    print("   Line Bot Webhook: /callback")
    if WEB_DISABLE_AUTH:
        print("   認證: 已停用 (WEB_DISABLE_AUTH=true)")
    else:
        print("   認證: 用戶名='admin'")
    app.run(host='0.0.0.0', port=port, debug=True)
