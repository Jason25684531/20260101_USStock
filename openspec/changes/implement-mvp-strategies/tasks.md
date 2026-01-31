# Tasks: MVP Strategies & Data Persistence

This change implements the "Momentum" and "Value" strategies, connects yfinance, and visualizes results on the dashboard.

## 1. Database Schema (The Memory)
- [x] **1.1 Market Data Table**
    - Create `database/init/01_market_data.sql`:
        - `market_data`: (symbol, date, open, high, low, close, volume, pe_ratio, pb_ratio). Primary Key (symbol, date).
- [x] **1.2 Backtest Results Table**
    - Create `database/init/02_results.sql`:
        - `backtest_runs`: (id, strategy_name, start_date, end_date, total_return, sharpe, max_drawdown, created_at).
        - `equity_curve`: (run_id, date, equity_value).
        - `trade_logs`: (run_id, symbol, entry_date, exit_date, entry_price, exit_price, pnl).

## 2. Python Strategy Engine (The Brain)
- [x] **2.1 Database Adapter**
    - Implement `strategies/src/adapters/database.py`:
        - `save_market_data(df, symbol)`: Upsert logic.
        - `save_backtest_run(portfolio, strategy_name)`: Parse vbt Portfolio and save to 3 result tables.
- [x] **2.2 Market Data Loader**
    - Implement `strategies/src/adapters/market_data.py`:
        - Use `yfinance` to fetch OHLCV + Fundamental data (PE/PB).
        - Function: `download_and_save(symbols=['SPY', 'QQQ', 'AAPL', 'NVDA'])`.
- [x] **2.3 Strategy Implementation**
    - Implement `strategies/src/strategies/momentum.py`: Logic: Close > Max(200).
    - Implement `strategies/src/strategies/value.py`: Logic: PE<15 & PB<1.5.
- [x] **2.4 Main Execution Loop**
    - Update `strategies/src/main.py`:
        1. Download data for a predefined list of stocks.
        2. Run Momentum Strategy -> Save Results.
        3. Run Value Strategy -> Save Results.

## 3. Web Dashboard (The View)
- [x] **3.1 Backend API**
    - Update `web/app.py`:
        - `GET /api/strategies`: List all strategies run.
        - `GET /api/run/<id>/equity`: Return equity curve for Chart.js.
- [x] **3.2 Frontend UI**
    - Update `web/templates/index.html`:
        - Add a dropdown to select Strategy Run.
        - Render Chart.js line chart for the selected run.

## 4. Verification
- [x] **4.1 Docker Integration**
    - Ensure `docker-compose.yml` links db, strategy, and web correctly.
- [x] **4.2 End-to-End Test**
    - Run `docker-compose up`.
    - Check terminal: "Saved Momentum run to DB", "Saved Value run to DB".
    - Check Browser (localhost:5000): Charts are visible and interactive.