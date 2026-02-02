"""
Alpaca Broker Adapter for Paper Trading.

This module handles all interactions with the Alpaca Paper Trading API,
providing a safe interface for order execution and position management.

Security Features:
- Hardcoded PAPER endpoint to prevent accidental real-money trading
- Max order value safety cap ($10,000)
- Buying power validation before order submission
- Secure secret management via Docker Secrets

Author: Quant System
Created: 2026-02-02
"""

import alpaca_trade_api as tradeapi
from typing import Dict, Optional, List
from decimal import Decimal
from utils.security import require_secret


class AlpacaBroker:
    """
    Alpaca Paper Trading Broker Adapter.
    
    This adapter provides a safe interface to Alpaca's Paper Trading API.
    The base_url is HARDCODED to the paper trading endpoint to prevent
    accidental execution on real accounts.
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
                f"Ensure alpaca_key.txt and alpaca_secret.txt exist in .secrets/"
            )
        
        # Initialize Alpaca API client
        try:
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
