"""
數據庫適配器 - 處理市場數據和回測結果的持久化
"""
import os
from datetime import datetime
from typing import Optional
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

# 使用絕對導入
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.security import get_secret


class DatabaseAdapter:
    """數據庫適配器，處理所有數據庫操作"""
    
    def __init__(self):
        """初始化數據庫連接"""
        db_host = os.getenv('DB_HOST', 'localhost')
        db_port = os.getenv('DB_PORT', '3306')
        db_user = os.getenv('DB_USER', 'root')
        # 使用 Docker Secrets 獲取密碼
        db_pass = get_secret('db_root_password', default=os.getenv('DB_PASSWORD', 'rootpassword'))
        db_name = os.getenv('DB_NAME', 'usstock')
        
        connection_string = (
            f"mysql+mysqlconnector://{db_user}:{db_pass}@"
            f"{db_host}:{db_port}/{db_name}?charset=utf8mb4"
        )
        
        self.engine: Engine = create_engine(connection_string, echo=False)
        print(f"✅ 數據庫連接已建立: {db_host}:{db_port}/{db_name}")
    
    def save_market_data(self, df: pd.DataFrame, symbol: str) -> int:
        """
        保存市場數據到數據庫（使用 UPSERT 邏輯）
        
        Args:
            df: 包含 OHLCV 數據的 DataFrame
            symbol: 股票代碼
            
        Returns:
            插入的行數
        """
        if df.empty:
            print(f"⚠️  {symbol}: 數據為空，跳過保存")
            return 0
        
        # 準備數據
        df = df.copy()
        df['symbol'] = symbol
        
        # 重命名列以匹配數據庫表結構
        column_mapping = {
            'Open': 'open',
            'High': 'high',
            'Low': 'low',
            'Close': 'close',
            'Volume': 'volume',
            'Adj Close': 'adj_close'
        }
        df = df.rename(columns=column_mapping)
        
        # 如果沒有 adj_close，使用 close 作為預設值
        if 'adj_close' not in df.columns:
            df['adj_close'] = df['close']
        
        # 確保索引是 datetime 並命名為 timestamp
        df.index.name = 'timestamp'
        df = df.reset_index()
        
        # 選擇需要的列（只選擇存在的列）
        columns_to_save = [
            'symbol', 'timestamp', 'open', 'high', 'low', 
            'close', 'volume', 'adj_close'
        ]
        
        # 添加可選列（如果存在）
        if 'pe_ratio' in df.columns:
            columns_to_save.append('pe_ratio')
        if 'pb_ratio' in df.columns:
            columns_to_save.append('pb_ratio')
        
        df = df[columns_to_save]
        
        # 使用 INSERT ... ON DUPLICATE KEY UPDATE
        try:
            # 先嘗試批量插入
            rows_inserted = df.to_sql(
                'market_data',
                self.engine,
                if_exists='append',
                index=False,
                method='multi'
            )
            print(f"✅ {symbol}: 成功保存 {rows_inserted} 行市場數據")
            return rows_inserted
        except Exception as e:
            # 如果有重複鍵，使用逐行 UPSERT
            print(f"⚠️  {symbol}: 檢測到重複數據，使用 UPSERT 模式")
            rows_updated = 0
            
            with self.engine.begin() as conn:
                for _, row in df.iterrows():
                    query = text("""
                        INSERT INTO market_data 
                        (symbol, timestamp, open, high, low, close, volume, adj_close)
                        VALUES (:symbol, :timestamp, :open, :high, :low, :close, :volume, :adj_close)
                        ON DUPLICATE KEY UPDATE
                            open = VALUES(open),
                            high = VALUES(high),
                            low = VALUES(low),
                            close = VALUES(close),
                            volume = VALUES(volume),
                            adj_close = VALUES(adj_close)
                    """)
                    conn.execute(query, row.to_dict())
                    rows_updated += 1
            
            print(f"✅ {symbol}: UPSERT 完成，處理 {rows_updated} 行")
            return rows_updated
    
    def save_backtest_run(
        self, 
        portfolio, 
        strategy_name: str,
        start_date: str,
        end_date: str
    ) -> int:
        """
        保存回測結果到數據庫
        
        Args:
            portfolio: VectorBT Portfolio 對象
            strategy_name: 策略名稱
            start_date: 開始日期
            end_date: 結束日期
            
        Returns:
            backtest_run 的 ID
        """
        try:
            # 提取統計數據
            stats = portfolio.stats()
            
            # 準備回測運行數據
            run_data = {
                'strategy_name': strategy_name,
                'start_date': start_date,
                'end_date': end_date,
                'total_return': float(stats.get('Total Return [%]', 0) / 100),
                'sharpe_ratio': float(stats.get('Sharpe Ratio', 0)),
                'max_drawdown': float(stats.get('Max Drawdown [%]', 0) / 100)
            }
            
            # 插入 backtest_runs
            with self.engine.begin() as conn:
                result = conn.execute(
                    text("""
                        INSERT INTO backtest_runs 
                        (strategy_name, start_date, end_date, total_return, sharpe_ratio, max_drawdown)
                        VALUES (:strategy_name, :start_date, :end_date, :total_return, :sharpe_ratio, :max_drawdown)
                    """),
                    run_data
                )
                run_id = result.lastrowid
            
            # 保存權益曲線
            equity_curve = portfolio.value()
            if isinstance(equity_curve, pd.Series):
                equity_df = pd.DataFrame({
                    'run_id': run_id,
                    'date': equity_curve.index,
                    'equity_value': equity_curve.values
                })
                
                equity_df.to_sql(
                    'equity_curve',
                    self.engine,
                    if_exists='append',
                    index=False,
                    method='multi'
                )
                print(f"✅ 權益曲線已保存: {len(equity_df)} 個數據點")
            
            # 保存交易記錄
            trades = portfolio.trades.records_readable
            if not trades.empty:
                trade_logs = pd.DataFrame({
                    'run_id': run_id,
                    'symbol': trades.get('Column', 'N/A'),
                    'entry_date': trades['Entry Timestamp'].dt.date if 'Entry Timestamp' in trades else None,
                    'exit_date': trades['Exit Timestamp'].dt.date if 'Exit Timestamp' in trades else None,
                    'entry_price': trades.get('Entry Price', 0),
                    'exit_price': trades.get('Exit Price', 0),
                    'pnl': trades.get('PnL', 0)
                })
                
                trade_logs.to_sql(
                    'trade_logs',
                    self.engine,
                    if_exists='append',
                    index=False,
                    method='multi'
                )
                print(f"✅ 交易記錄已保存: {len(trade_logs)} 筆交易")
            
            print(f"✅ {strategy_name}: 回測結果已保存 (run_id={run_id})")
            return run_id
            
        except Exception as e:
            print(f"❌ 保存回測結果失敗: {str(e)}")
            raise
    
    def get_market_data(
        self, 
        symbol: str, 
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> pd.DataFrame:
        """
        從數據庫讀取市場數據
        
        Args:
            symbol: 股票代碼
            start_date: 開始日期 (YYYY-MM-DD)
            end_date: 結束日期 (YYYY-MM-DD)
            
        Returns:
            市場數據 DataFrame
        """
        query = "SELECT * FROM market_data WHERE symbol = :symbol"
        params = {'symbol': symbol}
        
        if start_date:
            query += " AND timestamp >= :start_date"
            params['start_date'] = start_date
        
        if end_date:
            query += " AND timestamp <= :end_date"
            params['end_date'] = end_date
        
        query += " ORDER BY timestamp ASC"
        
        df = pd.read_sql(text(query), self.engine, params=params)
        
        if not df.empty:
            df.set_index('timestamp', inplace=True)
        
        return df
    
    def save_fundamentals(self, fundamentals: dict, symbol: str, data_date: str = None) -> bool:
        """
        保存基本面數據到數據庫
        
        Args:
            fundamentals: 基本面數據字典
            symbol: 股票代碼
            data_date: 數據日期，默認為今天
            
        Returns:
            是否保存成功
        """
        if not fundamentals:
            return False
        
        if data_date is None:
            from datetime import date
            data_date = date.today().isoformat()
        
        try:
            with self.engine.begin() as conn:
                query = text("""
                    INSERT INTO stock_fundamentals 
                    (symbol, data_date, pe_ratio, peg_ratio, pb_ratio, 
                     revenue_growth_yoy, earnings_growth_yoy, 
                     inst_ownership_pct, inst_holders_count, market_cap, forward_pe)
                    VALUES 
                    (:symbol, :data_date, :pe_ratio, :peg_ratio, :pb_ratio,
                     :revenue_growth_yoy, :earnings_growth_yoy,
                     :inst_ownership_pct, :inst_holders_count, :market_cap, :forward_pe)
                    ON DUPLICATE KEY UPDATE
                    pe_ratio = VALUES(pe_ratio),
                    peg_ratio = VALUES(peg_ratio),
                    pb_ratio = VALUES(pb_ratio),
                    revenue_growth_yoy = VALUES(revenue_growth_yoy),
                    earnings_growth_yoy = VALUES(earnings_growth_yoy),
                    inst_ownership_pct = VALUES(inst_ownership_pct),
                    inst_holders_count = VALUES(inst_holders_count),
                    market_cap = VALUES(market_cap),
                    forward_pe = VALUES(forward_pe),
                    updated_at = CURRENT_TIMESTAMP
                """)
                
                conn.execute(query, {
                    'symbol': symbol,
                    'data_date': data_date,
                    'pe_ratio': fundamentals.get('pe_ratio'),
                    'peg_ratio': fundamentals.get('peg_ratio'),
                    'pb_ratio': fundamentals.get('pb_ratio'),
                    'revenue_growth_yoy': fundamentals.get('revenue_growth_yoy'),
                    'earnings_growth_yoy': fundamentals.get('earnings_growth_yoy'),
                    'inst_ownership_pct': fundamentals.get('inst_ownership_pct'),
                    'inst_holders_count': fundamentals.get('inst_holders_count'),
                    'market_cap': fundamentals.get('market_cap'),
                    'forward_pe': fundamentals.get('forward_pe')
                })
                
            print(f"✅ {symbol}: 基本面數據已保存")
            return True
            
        except Exception as e:
            print(f"❌ {symbol}: 保存基本面數據失敗: {str(e)}")
            return False
    
    def close(self):
        """關閉數據庫連接"""
        if self.engine:
            self.engine.dispose()
            print("✅ 數據庫連接已關閉")
