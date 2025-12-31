# Quant System Project Context

## System Philosophy
- **Objective**: High-frequency, low-risk US stock quantitative trading system.
- **Core Principles**:
  - **Security First**: Zero Trust for API keys; use Docker Secrets (no hardcoded keys).
  - **Deterministic Execution**: Spec-Driven Development (SDD) via OpenSpec.
  - **Deployment Gap Elimination**: Use StrateQueue to bridge VectorBT and Alpaca.

## Technology Stack
- **Infrastructure**: Docker, Docker Compose (Microservices), MySQL 8.0.
- **Language**: Python 3.10+ (Type Hints required).
- **Core Libraries**: 
  - `vectorbt` (Vectorized backtesting, strictly no loops).
  - `sqlalchemy` (Database ORM).
  - `flask` + `line-bot-sdk` (Web/Interaction).
- **Frontend**: HTML5, Bootstrap 5, Vanilla JS (Chart.js).
- **Tools**: VSCode, Claude Code, DBeaver.

## Architecture Guidelines
- **Microservices**: 
  - `db`: MySQL persistence.
  - `strategy_engine`: Python/VectorBT logic.
  - `web_dashboard`: Flask + LineBot.
- **Data Flow**: Market Data -> DB -> Strategy -> Risk Check -> Execution.

## Coding Standards
- **Python**: Google Docstrings, Pylint compliant.
- **Secrets**: Must be read from `/run/secrets/` in Docker, fall back to ENV only for local dev.
- **Testing**: All strategies require unit tests for edge cases (e.g., zero volume).