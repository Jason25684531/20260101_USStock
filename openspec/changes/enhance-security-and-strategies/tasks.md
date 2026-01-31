# Tasks: Security Hardening & Multi-Factor Strategy Expansion

This change hardens the system security using Docker Secrets and expands the strategy engine with Chips, Advanced Technicals (ATR), and Fundamental (PEG) logic based on uploaded research.

## 1. Security Hardening (Priority: High)
- [x] **1.1 Implement Docker Secrets**
    - Create `.secrets/` directory (ensure it's in `.gitignore`).
    - Create `db_password.txt`, `alpaca_key.txt`, `web_password.txt`.
    - Update `docker-compose.yml` to use `secrets` driver instead of `environment` variables for sensitive data.
- [x] **1.2 Secure Python Logic**
    - Update `strategies/src/utils/security.py`: Enhance `get_secret` to strictly read from `/run/secrets/` in production.
- [x] **1.3 Web Dashboard Authentication**
    - Update `web/app.py`: Implement `Flask-HTTPAuth` or simple decorator to require username/password for all routes.

## 2. Data Layer Expansion (Chips & Fundamentals)
- [x] **2.1 Enhanced Data Loader**
    - Update `strategies/src/adapters/market_data.py`:
    - Add function `fetch_fundamentals(symbol)`: Get `institutionalHolders`, `pegRatio`, `revenueGrowth` via `yfinance`.
- [x] **2.2 Schema Update**
    - Create `database/init/05_fundamental_chips.sql`:
    - Alter `market_data` or create `stock_fundamentals` table to store `inst_ownership_pct`, `peg_ratio`, `revenue_growth_yoy`.

## 3. Advanced Strategy Implementation
- [x] **3.1 Strategy: Chips & Momentum (Smart Money)**
    - Create `strategies/src/strategies/chips_momentum.py`.
    - Logic: Buy if `Close > SMA(50)` AND `Institutional Ownership > 60%`.
- [x] **3.2 Strategy: Growth (PEG)**
    - Create `strategies/src/strategies/growth_peg.py`.
    - Logic: Buy if `PEG < 1.5` AND `Revenue Growth > 20%`.
- [x] **3.3 Risk Management: ATR Trailing Stop**
    - Update `strategies/src/core/backtest.py`.
    - Implement `apply_atr_stop(entry_price, current_price, atr_value, multiplier=2.0)`.

## 4. Visualization & Reporting
- [x] **4.1 Update Dashboard**
    - Update `web/templates/index.html`: Add labels to show which strategy (Chips/PEG) generated the run.
    - Add a "Risk Metrics" chart showing Drawdown vs. ATR.

## 5. Verification
- [x] **5.1 Security Test**
    - Verify `docker inspect` does NOT show passwords.
    - Verify accessing `http://localhost:5000` prompts for password.
- [x] **5.2 Strategy Test**
    - Run the new strategies on 'NVDA' and 'TSLA'.
    - Check DB for saved results.