"""
Broker Adapters for Trading System.

This module provides two broker implementations:
1. AlpacaBroker - For Alpaca Paper Trading API integration (optional)
2. MockBroker - For pure local simulation (no external API required)

Security Features:
- Hardcoded PAPER endpoint to prevent accidental real-money trading
- Max order value safety cap ($10,000)
- Buying power validation before order submission
- Secure secret management via environment variables

Author: Quant System
Created: 2026-02-02
Updated: 2026-02-09 - Added MockBroker for local simulation
"""

import os
import json
from pathlib import Path
from typing import Dict, Optional, List
from decimal import Decimal
from datetime import datetime
from utils.security import require_secret, get_secret


class AlpacaBroker:
    """
    Alpaca Paper Trading Broker Adapter.
    
    This adapter provides a safe interface to Alpaca's Paper Trading API.
    The base_url is HARDCODED to the paper trading endpoint to prevent
    accidental execution on real accounts.
    
    NOTE: This is optional. Use MockBroker for pure local simulation.
    """
    
    # 🔒 SECURITY: Hardcoded Paper Trading endpoint
    PAPER_BASE_URL = "https://paper-api.alpaca.markets"
    
    # 🔒 RISK MANAGEMENT: Max order value to prevent fat-finger errors
    MAX_ORDER_VALUE = 10000.0  # $10,000 safety cap
    
    def __init__(self, use_paper: bool = True):
        """
        Initialize the Alpaca Broker connection.
        
        Args:
            use_paper: MUST be True. Hardcoded safety to prevent real trading.
            
        Raises:
            ValueError: If use_paper is False (safety check).
            ConnectionError: If unable to connect to Alpaca API.
        """
        import alpaca_trade_api as tradeapi
        
        if not use_paper:
            raise ValueError(
                "❌ Real trading is not supported. This system is designed for "
                "PAPER TRADING ONLY. Set use_paper=True."
            )
        
        # Load API credentials securely
        try:
            api_key = require_secret("alpaca_key")
            api_secret = require_secret("alpaca_secret")
        except ValueError as e:
            raise ConnectionError(
                f"Unable to load Alpaca credentials: {e}\n"
                f"Ensure ALPACA_KEY and ALPACA_SECRET are set in .env"
            )
        
        # Initialize Alpaca API client
        try:
            import alpaca_trade_api as tradeapi
            self.api = tradeapi.REST(
                key_id=api_key,
                secret_key=api_secret,
                base_url=self.PAPER_BASE_URL,
                api_version='v2'
            )
            
            # Verify connection
            account = self.api.get_account()
            print(f"✅ Connected to Alpaca Paper Trading")
            print(f"   Account ID: {account.id}")
            print(f"   Buying Power: ${float(account.buying_power):,.2f}")
            
        except Exception as e:
            raise ConnectionError(f"Failed to connect to Alpaca API: {e}")
    
    def get_account(self) -> Dict[str, float]:
        """
        Get current account information.
        
        Returns:
            Dict with keys:
                - cash: Available cash balance
                - buying_power: Total buying power (includes margin)
                - equity: Total account equity
                - portfolio_value: Current portfolio value
        """
        try:
            account = self.api.get_account()
            return {
                'cash': float(account.cash),
                'buying_power': float(account.buying_power),
                'equity': float(account.equity),
                'portfolio_value': float(account.portfolio_value)
            }
        except Exception as e:
            print(f"❌ Error fetching account info: {e}")
            raise
    
    def get_positions(self) -> Dict[str, int]:
        """
        Get current positions (holdings).
        
        Returns:
            Dict mapping symbol -> quantity (e.g., {'AAPL': 10, 'SPY': 5})
        """
        try:
            positions = self.api.list_positions()
            return {
                pos.symbol: int(pos.qty)
                for pos in positions
            }
        except Exception as e:
            print(f"❌ Error fetching positions: {e}")
            raise
    
    def get_position(self, symbol: str) -> int:
        """
        Get current position for a specific symbol.
        
        Args:
            symbol: Stock ticker symbol (e.g., 'AAPL')
            
        Returns:
            Current quantity (0 if no position exists)
        """
        try:
            position = self.api.get_position(symbol)
            return int(position.qty)
        except tradeapi.rest.APIError as e:
            # Position not found is not an error
            if 'position does not exist' in str(e).lower():
                return 0
            raise
        except Exception as e:
            print(f"❌ Error fetching position for {symbol}: {e}")
            raise
    
    def get_current_price(self, symbol: str) -> float:
        """
        Get the current market price for a symbol.
        
        Args:
            symbol: Stock ticker symbol
            
        Returns:
            Current price (last trade or bid/ask midpoint)
        """
        try:
            # Get latest trade
            latest_trade = self.api.get_latest_trade(symbol)
            return float(latest_trade.price)
        except Exception as e:
            print(f"⚠️  Could not get latest trade for {symbol}: {e}")
            # Fallback to last quote
            try:
                quote = self.api.get_latest_quote(symbol)
                return (float(quote.ask_price) + float(quote.bid_price)) / 2
            except Exception as e2:
                print(f"❌ Error fetching price for {symbol}: {e2}")
                raise
    
    def check_risk(self, symbol: str, qty: int, price: float) -> tuple[bool, str]:
        """
        Pre-trade risk validation.
        
        Checks:
        1. Order value < MAX_ORDER_VALUE ($10,000)
        2. Sufficient buying power for buy orders
        
        Args:
            symbol: Stock ticker symbol
            qty: Order quantity (positive for buy, negative for sell)
            price: Current market price
            
        Returns:
            Tuple of (is_valid, error_message)
            - (True, "") if checks pass
            - (False, "reason") if checks fail
        """
        order_value = abs(qty) * price
        
        # Rule 1: Max order value check
        if order_value > self.MAX_ORDER_VALUE:
            return False, (
                f"Order value ${order_value:,.2f} exceeds safety cap "
                f"of ${self.MAX_ORDER_VALUE:,.2f}"
            )
        
        # Rule 2: Buying power check (only for buy orders)
        if qty > 0:
            account = self.get_account()
            if order_value > account['buying_power']:
                return False, (
                    f"Insufficient buying power: need ${order_value:,.2f}, "
                    f"have ${account['buying_power']:,.2f}"
                )
        
        return True, ""
    
    def submit_order(
        self,
        symbol: str,
        qty: int,
        side: str,
        order_type: str = 'market',
        time_in_force: str = 'day',
        limit_price: Optional[float] = None
    ) -> Dict:
        """
        Submit an order to Alpaca.
        
        Args:
            symbol: Stock ticker symbol
            qty: Order quantity (must be positive)
            side: 'buy' or 'sell'
            order_type: 'market', 'limit', 'stop', 'stop_limit'
            time_in_force: 'day', 'gtc', 'ioc', 'fok'
            limit_price: Required for limit orders
            
        Returns:
            Dict with order details:
                - order_id: Alpaca order ID
                - symbol: Ticker symbol
                - qty: Quantity
                - side: buy/sell
                - status: Order status
                - filled_qty: Quantity filled
                - filled_avg_price: Average fill price
                
        Raises:
            ValueError: If pre-trade checks fail
        """
        if qty <= 0:
            raise ValueError(f"Quantity must be positive, got {qty}")
        
        # Get current price for risk check
        current_price = self.get_current_price(symbol)
        
        # Pre-trade risk validation
        check_qty = qty if side == 'buy' else -qty
        is_valid, error_msg = self.check_risk(symbol, check_qty, current_price)
        if not is_valid:
            raise ValueError(f"Risk check failed: {error_msg}")
        
        # Submit order
        try:
            order = self.api.submit_order(
                symbol=symbol,
                qty=qty,
                side=side,
                type=order_type,
                time_in_force=time_in_force,
                limit_price=limit_price
            )
            
            print(f"✅ Order submitted: {side.upper()} {qty} {symbol} @ {order_type}")
            print(f"   Order ID: {order.id}")
            print(f"   Status: {order.status}")
            
            return {
                'order_id': order.id,
                'symbol': order.symbol,
                'qty': int(order.qty),
                'side': order.side,
                'type': order.type,
                'status': order.status,
                'filled_qty': int(order.filled_qty) if order.filled_qty else 0,
                'filled_avg_price': float(order.filled_avg_price) if order.filled_avg_price else 0.0,
                'submitted_at': str(order.submitted_at),
            }
            
        except Exception as e:
            print(f"❌ Order submission failed: {e}")
            raise
    
    def cancel_order(self, order_id: str) -> bool:
        """
        Cancel a pending order.
        
        Args:
            order_id: Alpaca order ID
            
        Returns:
            True if cancelled successfully, False otherwise
        """
        try:
            self.api.cancel_order(order_id)
            print(f"✅ Order {order_id} cancelled")
            return True
        except Exception as e:
            print(f"❌ Failed to cancel order {order_id}: {e}")
            return False
    
    def get_order(self, order_id: str) -> Dict:
        """
        Get status of a specific order.
        
        Args:
            order_id: Alpaca order ID
            
        Returns:
            Dict with order details
        """
        try:
            order = self.api.get_order(order_id)
            return {
                'order_id': order.id,
                'symbol': order.symbol,
                'qty': int(order.qty),
                'side': order.side,
                'type': order.type,
                'status': order.status,
                'filled_qty': int(order.filled_qty) if order.filled_qty else 0,
                'filled_avg_price': float(order.filled_avg_price) if order.filled_avg_price else 0.0,
            }
        except Exception as e:
            print(f"❌ Error fetching order {order_id}: {e}")
            raise
    
    def close_position(self, symbol: str) -> bool:
        """
        Close entire position for a symbol (market order).
        
        Args:
            symbol: Stock ticker symbol
            
        Returns:
            True if position closed successfully
        """
        try:
            self.api.close_position(symbol)
            print(f"✅ Closed position: {symbol}")
            return True
        except Exception as e:
            print(f"❌ Failed to close position {symbol}: {e}")
            return False


class MockBroker:
    """
    Mock Broker for Pure Local Simulation.
    
    This broker simulates trading without any external API dependencies.
    All trades are executed instantly at the current market price and
    logged to the database.
    
    Features:
    - No Alpaca API required
    - Instant execution at market price
    - Persistent state (JSON + MySQL)
    - Starting capital: $100,000
    """
    
    # 🔒 RISK MANAGEMENT: Max order value to prevent fat-finger errors
    MAX_ORDER_VALUE = 10000.0  # $10,000 safety cap
    
    # 💰 TRANSACTION COST: Commission + slippage approximation
    COMMISSION_RATE = 0.001  # 0.1%
    
    # Default starting capital
    INITIAL_CASH = 100000.0  # $100,000
    
    def __init__(self, state_file: Optional[str] = None):
        """
        Initialize the Mock Broker.
        
        Args:
            state_file: Path to JSON file for persisting broker state.
                       Defaults to /app/data/mock_broker_state.json
        """
        if state_file is None:
            state_file = "/app/data/mock_broker_state.json"
        
        self.state_file = Path(state_file)
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Load or initialize state
        self.state = self._load_state()
        
        print(f"✅ Mock Broker 已初始化")
        print(f"   現金: ${self.state['cash']:,.2f}")
        print(f"   持倉數量: {len(self.state['positions'])}")
        if self.state['positions']:
            print(f"   持倉: {self.state['positions']}")
    
    def _load_state(self) -> dict:
        """Load broker state from JSON file or create new state."""
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r') as f:
                    state = json.load(f)
                print(f"📂 已載入狀態檔案: {self.state_file}")
                return state
            except Exception as e:
                print(f"⚠️  無法載入狀態檔案: {e}，使用初始值")
        
        # Create new state
        return {
            'cash': self.INITIAL_CASH,
            'positions': {},  # {symbol: qty}
            'orders': [],  # Historical orders
            'created_at': datetime.now().isoformat()
        }
    
    def _save_state(self):
        """Save current state to JSON file."""
        try:
            with open(self.state_file, 'w') as f:
                json.dump(self.state, f, indent=2)
        except Exception as e:
            print(f"⚠️  無法保存狀態檔案: {e}")
    
    def get_account(self, prices: Optional[Dict[str, float]] = None) -> Dict[str, float]:
        """
        Get current account information.
        
        Args:
            prices: {symbol: current_price} 用於計算持倉市值（可選）
                    若不提供，equity = cash（向後相容）
        
        Returns:
            Dict with keys:
                - cash: Available cash balance
                - buying_power: Total buying power (same as cash for mock)
                - equity: Total account equity (cash + positions)
                - portfolio_value: Current portfolio value (positions only)
        """
        cash = self.state['cash']
        
        # 計算持倉市值
        position_value = 0.0
        if prices:
            for sym, qty in self.state['positions'].items():
                if sym in prices and prices[sym] > 0:
                    position_value += qty * prices[sym]
        
        equity = cash + position_value
        
        return {
            'cash': cash,
            'buying_power': cash,
            'equity': equity,
            'portfolio_value': position_value,
        }
    
    def get_positions(self) -> Dict[str, int]:
        """
        Get current positions (holdings).
        
        Returns:
            Dict mapping symbol -> quantity (e.g., {'AAPL': 10, 'SPY': 5})
        """
        return dict(self.state['positions'])
    
    def get_position(self, symbol: str) -> int:
        """
        Get current position for a specific symbol.
        
        Args:
            symbol: Stock ticker symbol (e.g., 'AAPL')
            
        Returns:
            Current quantity (0 if no position exists)
        """
        return self.state['positions'].get(symbol, 0)
    
    def check_risk(self, symbol: str, qty: int, price: float) -> tuple[bool, str]:
        """
        Pre-trade risk validation.
        
        Checks:
        1. Order value < MAX_ORDER_VALUE ($10,000)
        2. Sufficient cash for buy orders
        3. Sufficient shares for sell orders
        
        Args:
            symbol: Stock ticker symbol
            qty: Order quantity (positive for buy, negative for sell)
            price: Current market price
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        order_value = abs(qty) * price
        
        # Rule 1: Max order value check
        if order_value > self.MAX_ORDER_VALUE:
            return False, (
                f"訂單金額 ${order_value:,.2f} 超過安全上限 "
                f"${self.MAX_ORDER_VALUE:,.2f}"
            )
        
        # Rule 2: Cash check for buy orders
        if qty > 0:
            if order_value > self.state['cash']:
                return False, (
                    f"現金不足: 需要 ${order_value:,.2f}, "
                    f"擁有 ${self.state['cash']:,.2f}"
                )
        
        # Rule 3: Share check for sell orders
        else:
            current_position = self.get_position(symbol)
            if abs(qty) > current_position:
                return False, (
                    f"持股不足: 需要 {abs(qty)} 股, "
                    f"擁有 {current_position} 股"
                )
        
        return True, ""
    
    def submit_order(
        self,
        symbol: str,
        qty: int,
        side: str,
        order_type: str = 'market',
        time_in_force: str = 'day',
        limit_price: Optional[float] = None,
        current_price: Optional[float] = None,
        confidence: Optional[float] = None,
        top_features: Optional[Dict] = None
    ) -> Dict:
        """
        Submit a simulated order.
        
        The order is executed INSTANTLY at the current market price.
        State is updated and logged to database.
        
        Args:
            symbol: Stock ticker symbol
            qty: Order quantity (must be positive)
            side: 'buy' or 'sell'
            order_type: 'market' (only market orders supported for now)
            time_in_force: Ignored for mock broker
            limit_price: Ignored for mock broker (instant execution)
            current_price: Current market price. If None, will fetch from yfinance
            
        Returns:
            Dict with order details
            
        Raises:
            ValueError: If pre-trade checks fail
        """
        if qty <= 0:
            raise ValueError(f"數量必須為正數, 收到 {qty}")
        
        # Determine actual quantity based on side
        actual_qty = qty if side == 'buy' else -qty
        
        # Get current price if not provided
        if current_price is None:
            from .market_data import get_latest_price
            current_price = get_latest_price(symbol)
            if current_price is None:
                raise ValueError(f"無法獲取 {symbol} 的當前價格")
        
        # Pre-trade risk validation
        is_valid, error_msg = self.check_risk(symbol, actual_qty, current_price)
        if not is_valid:
            raise ValueError(f"風險檢查失敗: {error_msg}")
        
        # Execute trade (instant fill at current price)
        order_value = qty * current_price
        commission = order_value * self.COMMISSION_RATE
        
        if side == 'buy':
            # Deduct cash (price + fee), add shares
            self.state['cash'] -= (order_value + commission)
            self.state['positions'][symbol] = self.state['positions'].get(symbol, 0) + qty
            net_price = current_price * (1 + self.COMMISSION_RATE)
        else:
            # Add cash (price - fee), deduct shares
            self.state['cash'] += (order_value - commission)
            self.state['positions'][symbol] = self.state['positions'].get(symbol, 0) - qty
            net_price = current_price * (1 - self.COMMISSION_RATE)
            
            # Remove position if qty reaches 0
            if self.state['positions'][symbol] == 0:
                del self.state['positions'][symbol]
        
        # Create order record
        order = {
            'order_id': f"mock_{datetime.now().strftime('%Y%m%d%H%M%S')}_{symbol}",
            'symbol': symbol,
            'qty': qty,
            'side': side,
            'type': order_type,
            'status': 'filled',
            'filled_qty': qty,
            'filled_avg_price': current_price,
            'net_price': net_price,
            'commission': commission,
            'submitted_at': datetime.now().isoformat(),
            'confidence': confidence,
            'top_features': top_features,
        }
        
        # Add to order history
        self.state['orders'].append(order)
        
        # Save state
        self._save_state()
        
        # Log to database
        self._log_to_database(order)
        
        print(f"✅ 模擬訂單已執行: {side.upper()} {qty} {symbol} @ ${current_price:.2f} (Net: ${net_price:.2f}, Fee: ${commission:.2f})")
        print(f"   訂單ID: {order['order_id']}")
        print(f"   剩餘現金: ${self.state['cash']:,.2f}")
        
        return order
    
    def _log_to_database(self, order: dict):
        """
        Log the simulated trade to MySQL database.
        
        Args:
            order: Order dictionary with trade details
        """
        try:
            from .database import DatabaseAdapter
            from sqlalchemy import text
            import json as _json
            
            db = DatabaseAdapter()
            
            # We'll use the trade_logs table, but with run_id = 0 for live simulation
            trade_data = {
                'run_id': 0,  # 0 indicates live simulation (not backtest)
                'symbol': order['symbol'],
                'entry_date': datetime.now().date(),
                'entry_price': order['filled_avg_price'],
                'pnl': 0.0,  # Will be calculated on exit
                'confidence': order.get('confidence'),
                'top_features': _json.dumps(order['top_features']) if order.get('top_features') else None,
            }
            
            with db.engine.begin() as conn:
                conn.execute(
                    text("""
                        INSERT INTO trade_logs 
                        (run_id, symbol, entry_date, entry_price, pnl, confidence, top_features)
                        VALUES (:run_id, :symbol, :entry_date, :entry_price, :pnl, :confidence, :top_features)
                    """),
                    trade_data
                )
            
            db.close()
            
        except Exception as e:
            print(f"⚠️  無法記錄交易到資料庫: {e}")
    
    def cancel_order(self, order_id: str) -> bool:
        """
        Cancel order (not supported for instant execution).
        
        Args:
            order_id: Order ID
            
        Returns:
            False (orders are executed instantly)
        """
        print(f"⚠️  Mock Broker 訂單即時執行，無法取消")
        return False
    
    def get_order(self, order_id: str) -> Optional[Dict]:
        """
        Get order by ID from history.
        
        Args:
            order_id: Order ID
            
        Returns:
            Order dict if found, None otherwise
        """
        for order in self.state['orders']:
            if order['order_id'] == order_id:
                return order
        return None
    
    def close_position(self, symbol: str) -> bool:
        """
        Close entire position for a symbol.
        
        Args:
            symbol: Stock ticker symbol
            
        Returns:
            True if closed successfully
        """
        qty = self.get_position(symbol)
        if qty == 0:
            print(f"⚠️  {symbol} 沒有持倉")
            return False
        
        try:
            self.submit_order(symbol, qty, 'sell')
            print(f"✅ 已平倉: {symbol}")
            return True
        except Exception as e:
            print(f"❌ 平倉失敗 {symbol}: {e}")
            return False

