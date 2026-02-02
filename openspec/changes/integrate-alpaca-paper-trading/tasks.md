# Tasks: Alpaca Paper Trading Integration

This change bridges the gap between simulation and reality by connecting the strategy engine to Alpaca's Paper Trading API for live order execution.

## 1. Infrastructure & Config
- [x] **1.1 Alpaca Credentials**
    - Ensure `alpaca_key.txt` and `alpaca_secret.txt` exist in `.secrets/`.
    - Update `docker-compose.yml` to inject these secrets into the `strategy_engine` service.
- [x] **1.2 Requirement Update**
    - Update `strategies/requirements.txt`: Ensure `alpaca-trade-api` is present.

## 2. Broker Adapter Implementation (The Hands)
- [x] **2.1 Create AlpacaBroker Class**
    - Implement `strategies/src/adapters/broker.py`.
    - Methods required:
        - `get_account()`: Returns cash & buying power.
        - `get_positions()`: Returns current holdings (symbol -> qty).
        - `submit_order(symbol, qty, side, type='market')`: Executes the trade.
    - **Security Constraint**: Must use `get_secret` to load keys. Base URL must default to Paper Trading (`https://paper-api.alpaca.markets`).

## 3. Execution Engine Update (The Brain)
- [x] **3.1 Live/Paper Mode Logic**
    - Modify `strategies/src/main.py`:
        - Add environment variable check: `TRADING_MODE` (default: 'backtest').
        - Initialize `AlpacaBroker` only if mode is 'paper' or 'live'.
- [x] **3.2 Order Execution Flow**
    - In `job()` function:
        1. Calculate Target Position (from Strategy).
        2. Get Current Position (from Broker).
        3. Calculate `Diff = Target - Current`.
        4. If `Diff != 0`: Execute Order.
        5. Log result to MySQL and send Line Notification.

## 4. Risk Guardrails (Safety)
- [x] **4.1 Pre-Trade Checks**
    - Implement `check_risk(symbol, qty, price)` in Broker Adapter.
    - Rule 1: Order value < $10,000 (Safety cap).
    - Rule 2: Cannot buy if Buying Power is insufficient.

## 5. Verification
- [x] **5.1 Connection Test**
    - Create `strategies/test_broker_connection.py` to verify API connectivity and print Account Equity.
    - Create `strategies/test_integration_logic.py` for code logic verification without API credentials.