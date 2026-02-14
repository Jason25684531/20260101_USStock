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
from flask import Flask, render_template, jsonify
from flask_httpauth import HTTPBasicAuth
from werkzeug.security import check_password_hash, generate_password_hash
from sqlalchemy import text
from datetime import datetime

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


# Aliases for backward compatibility (previously defined locally)
_table_exists = table_exists
_column_exists = column_exists

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

    try:
        with engine.connect() as conn:
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
                    return jsonify([])
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
        return jsonify({'error': str(e)}), 500


# ============================================
# 個股詳情 API
# ============================================
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
            # 最新推薦紀錄
            row = conn.execute(text("""
                SELECT scan_date, signal_type, total_score, ml_confidence,
                       current_price, support_1, support_2, resistance_1, resistance_2,
                       breakout_pass, acceleration_pass, peg_pass, dupont_pass,
                       institutional_pass, volume_structure_pass, money_flow_pass,
                       multi_tf_momentum_pass, relative_strength_pass,
                       earnings_quality_pass, sector_rotation_pass,
                       pe_ratio, peg_ratio, pb_ratio, roe,
                       sector, macro_regime, strategy_details, total_strategies
                FROM daily_recommendations
                WHERE symbol = :sym
                ORDER BY scan_date DESC
                LIMIT 1
            """), {'sym': symbol}).first()

            if not row:
                return jsonify({'error': f'{symbol} 無推薦資料'}), 404

            # 基本面（從 stock_fundamentals 補齊）
            fund_row = conn.execute(text("""
                SELECT pe_ratio, peg_ratio, pb_ratio, market_cap,
                       revenue_growth, earnings_growth,
                       institutional_ownership, insider_ownership_pct,
                       short_ratio, gross_margin, profit_margin,
                       free_cashflow, roe, sector
                FROM stock_fundamentals
                WHERE symbol = :sym
                ORDER BY data_date DESC
                LIMIT 1
            """), {'sym': symbol}).first()

            strategies = {
                'breakout':          bool(row[9]),
                'acceleration':      bool(row[10]),
                'peg':               bool(row[11]),
                'dupont':            bool(row[12]),
                'institutional':     bool(row[13]) if row[13] is not None else None,
                'volume_structure':  bool(row[14]) if row[14] is not None else None,
                'money_flow':        bool(row[15]) if row[15] is not None else None,
                'multi_tf_momentum': bool(row[16]) if row[16] is not None else None,
                'relative_strength': bool(row[17]) if row[17] is not None else None,
                'earnings_quality':  bool(row[18]) if row[18] is not None else None,
                'sector_rotation':   bool(row[19]) if row[19] is not None else None,
            }

            fundamentals = {}
            if fund_row:
                fundamentals = {
                    'pe_ratio':       float(fund_row[0]) if fund_row[0] else None,
                    'peg_ratio':      float(fund_row[1]) if fund_row[1] else None,
                    'pb_ratio':       float(fund_row[2]) if fund_row[2] else None,
                    'market_cap':     float(fund_row[3]) if fund_row[3] else None,
                    'revenue_growth': float(fund_row[4]) if fund_row[4] else None,
                    'earnings_growth':float(fund_row[5]) if fund_row[5] else None,
                    'institutional_ownership': float(fund_row[6]) if fund_row[6] else None,
                    'insider_ownership': float(fund_row[7]) if fund_row[7] else None,
                    'short_ratio':    float(fund_row[8]) if fund_row[8] else None,
                    'gross_margin':   float(fund_row[9]) if fund_row[9] else None,
                    'profit_margin':  float(fund_row[10]) if fund_row[10] else None,
                    'free_cashflow':  float(fund_row[11]) if fund_row[11] else None,
                    'roe':            float(fund_row[12]) if fund_row[12] else None,
                    'sector':         fund_row[13],
                }
            else:
                fundamentals = {
                    'pe_ratio':  float(row[20]) if row[20] else None,
                    'peg_ratio': float(row[21]) if row[21] else None,
                    'pb_ratio':  float(row[22]) if row[22] else None,
                    'roe':       float(row[23]) if row[23] else None,
                    'sector':    row[24],
                }

            details = None
            if row[26]:
                try:
                    details = json.loads(row[26]) if isinstance(row[26], str) else row[26]
                except Exception:
                    pass

            return jsonify({
                'symbol':       symbol,
                'scan_date':    str(row[0]),
                'signal':       row[1],
                'total_score':  float(row[2]) if row[2] else 0,
                'strategies':   strategies,
                'fundamentals': fundamentals,
                'ml': {
                    'confidence': float(row[3]) if row[3] else None,
                },
                'price': {
                    'current':     float(row[4]) if row[4] else 0,
                    'support_1':   float(row[5]) if row[5] else None,
                    'support_2':   float(row[6]) if row[6] else None,
                    'resistance_1':float(row[7]) if row[7] else None,
                    'resistance_2':float(row[8]) if row[8] else None,
                },
                'macro_regime':    row[25],
                'total_strategies':int(row[27]) if row[27] else 4,
                'strategy_details':details,
            })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


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
    try:
        with engine.connect() as conn:
            has_confidence = _column_exists(conn, 'trade_logs', 'confidence')
            conf_expr = 't.confidence' if has_confidence else 'NULL AS confidence'

            # 尚未出場的持倉
            rows = conn.execute(text(f"""
                SELECT t.symbol, t.entry_date, t.entry_price, {conf_expr},
                       r.strategy_name
                FROM trade_logs t
                JOIN backtest_runs r ON t.run_id = r.id
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
        return jsonify({'error': str(e)}), 500


# ============================================
# 宏觀指標 API
# ============================================
@app.route('/api/macro')
@auth.login_required
def get_macro():
    """
    取得宏觀經濟指標 + 最新 Regime

    Returns:
        JSON: {regime:{...}, indicators:{vix, yield_curve, unemployment, fed_rate, cpi}}
    """
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
        return jsonify({'error': str(e)}), 500


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
                sector_map = {
                    'AAPL': 'Technology', 'MSFT': 'Technology', 'NVDA': 'Technology', 'AMD': 'Technology',
                    'GOOGL': 'Communication', 'META': 'Communication', 'NFLX': 'Communication',
                    'AMZN': 'Consumer Discretionary', 'TSLA': 'Consumer Discretionary',
                    'JPM': 'Financials', 'BAC': 'Financials', 'V': 'Financials', 'MA': 'Financials',
                    'LLY': 'Healthcare', 'UNH': 'Healthcare', 'JNJ': 'Healthcare',
                    'XOM': 'Energy', 'CVX': 'Energy',
                }
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
        return jsonify({'error': str(e)}), 500


# ============================================
# 推薦日期列表 API
# ============================================
@app.route('/api/recommendations/dates')
@auth.login_required
def get_recommendation_dates():
    """取得所有有推薦資料的日期列表"""
    try:
        with engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT DISTINCT scan_date FROM daily_recommendations ORDER BY scan_date DESC LIMIT 60"
            ))
            dates = [str(row[0]) for row in rows]
            return jsonify({'dates': dates})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    port = int(os.getenv('WEB_PORT', '6688'))
    print("🚀 啟動 Flask 儀表板...")
    print(f"   DB: {DB_CONFIG['host']}:{DB_CONFIG['port']}:{DB_CONFIG['name']}")
    print(f"   訪問地址: http://0.0.0.0:{port}")
    print("   Line Bot Webhook: /callback")
    print("   認證: 用戶名='admin'")
    app.run(host='0.0.0.0', port=port, debug=True)