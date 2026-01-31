# Quant System Project Context

## 1. System Philosophy
- **Objective**: Institution-grade US Stock Quantitative Trading System (High Alpha, Low Risk).
- **Core Principles**:
  - **Data Persistence**: All backtest results (equity curves, trade logs) MUST be saved to MySQL. No "fire and forget".
  - **Vectorization**: Use `vectorbt` for all strategy calculations. No `for` loops for signal generation.
  - **Zero Trust Security**: API Keys (Alpaca/LineBot) must use Docker Secrets (`/run/secrets/`).

## 2. Technology Stack
- **Infrastructure**: Docker Compose (Microservices), MySQL 8.0.
- **Language**: Python 3.10+ (Type Hints required).
- **Data Source**: 
  - `yfinance`: For historical data (OHLCV) and fundamental data (PE, PB ratios).
- **Backtesting**: `vectorbt` (Vectorized Backtesting).
- **Web**: Flask (API) + Vanilla JS/Chart.js (Dashboard).

## 3. Core Strategies (Logic Definitions)
Based on "FinLab" and "Mr. Market" literature:

### Strategy A: Momentum 200 (動能策略)
- **Concept**: Trend Following / VCP.
- **Signal**:
  - **Entry**: Close price > Highest High of past 200 days.
  - **Exit**: Close price < 20-day Moving Average (Trailing Stop).
- **Universe**: S&P 500 constituents (approximated by top 500 US stocks by volume).

### Strategy B: Value Investing (價值策略)
- **Concept**: Undervalued High-Quality Stocks.
- **Signal**:
  - **Filter 1**: P/E Ratio (本益比) < 15.
  - **Filter 2**: P/B Ratio (股價淨值比) < 1.5.
  - **Filter 3**: Price > SMA(60) (Trend Filter).
- **Rebalance**: Quarterly.

## 4. Architecture & Data Flow
1.  **Ingest**: `MarketDataAdapter` fetches data from `yfinance`.
2.  **Store**: Raw market data saved to MySQL `market_data` table.
3.  **Compute**: `StrategyEngine` (VectorBT) queries MySQL -> runs logic -> generates signals.
4.  **Persist**: `DatabaseAdapter` saves `Portfolio` stats (Sharpe, Returns) and `Equity Curve` to MySQL.
5.  **Visualize**: Web Dashboard queries MySQL -> draws charts.