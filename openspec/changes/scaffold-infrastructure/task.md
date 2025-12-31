# Tasks: Infrastructure & MVP Backtest Engine

This change scaffolds the Docker microservices AND implements the first "Hello World" strategy to verify the backtesting engine.

## 1. Docker Environment Setup
- [x] **1.1 Create Docker Compose Config**
    - Create `docker-compose.yml` defining services: `db` (MySQL), `strategy_engine` (Python), `web_dashboard` (Flask).
    - Configure **Docker Secrets** mapping for all services (mapping `./.secrets/` to `/run/secrets/`).
    - Set `strategy_engine` to run `python src/main.py` on startup.
- [x] **1.2 Database Container**
    - Configure MySQL 8.0 service.
    - Create entrypoint script `database/init/01_schema.sql` to define a basic `market_data` table.

## 2. Python & Security Foundation
- [x] **2.1 Shared Security Module**
    - Implement `strategies/src/utils/security.py` with a `get_secret()` function.
    - Must prioritize `/run/secrets/` and support `.env` fallback for local dev.
- [x] **2.2 Python Dockerfiles**
    - Create `strategies/Dockerfile` installing dependencies from `requirements.txt`.
    - Create `web/Dockerfile` (basic scaffolding only).

## 3. Backtesting Engine (The "Brain")
- [x] **3.1 Data Adapter**
    - Implement `strategies/src/adapters/market_data.py`.
    - Function `fetch_data(symbol, period)` using `yfinance` to get DataFrame.
- [x] **3.2 VectorBT Strategy Logic**
    - Implement `strategies/src/core/backtest.py`.
    - Create function `run_sma_strategy(data, fast_window, slow_window)`.
    - Use `vectorbt` to calculate signals (CrossAbove/CrossBelow) and generate Portfolio stats (Total Return, Sharpe Ratio).
- [x] **3.3 Execution Entry Point**
    - Implement `strategies/src/main.py`.
    - Logic: Fetch 'SPY' data -> Run SMA Strategy -> Print performance report to console.

## 4. Project Configuration
- [x] **4.1 Config Files**
    - Generate `requirements.txt` (pinned versions).
    - Update `.gitignore` (exclude `.secrets/`, `venv/`).

## 5. Verification
- [x] **5.1 End-to-End Test**
    - Run `docker-compose up --build`.
    - Verify that `strategy_engine` container starts, downloads data, runs backtest, prints results, and exits successfully 0.