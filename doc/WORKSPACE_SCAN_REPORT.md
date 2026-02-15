# Comprehensive Workspace Scan Report

**Project:** US Stock Trading Strategy Engine  
**Path:** `D:\01_Project\20260101_USStock`  
**Generated:** 2026 (automated scan)

---

## 1. Full Directory Tree

```
D:\01_Project\20260101_USStock\
│
├── .claude/                          # Claude AI config
├── .env                              # Environment variables (local dev)
├── .git/                             # Git repository
├── .github/                          # GitHub Actions / CI
├── .gitignore
├── .dockerignore
├── .venv/                            # Python 3.11 virtual environment
│
├── docker-compose.yml                # Dev Docker Compose
├── prod.docker-compose.yml           # Production Docker Compose
├── requirements.txt                  # Top-level Python dependencies
├── test_linebot.ps1                  # PowerShell: Line Bot test script
├── verify_all.ps1                    # PowerShell: verification script
│
├── README.md
├── QUICK_START.md
├── ADVANCED_REFERENCE.md
├── COMMANDS_REFERENCE.md
├── FIXES_SUMMARY.md
├── LINEBOT_ARCHITECTURE_AND_TESTING.md
├── LINEBOT_COMPONENTS_AND_COMMANDS.md
├── LINEBOT_NGROK_GUIDE.md
├── LINEBOT_SETUP.md
├── LINEBOT_TROUBLESHOOTING.md
├── NGROK_ERROR_3004_FIX.md
│
├── data/
│   └── reports/
│       ├── line_sampling_20260215_233939.json
│       ├── ml_backtest_2024.csv
│       ├── regression_20260215_233607.json
│       └── regression_20260215_233900.json
│
├── database/
│   ├── my.cnf                        # MySQL config
│   └── init/
│       ├── 01_market_data.sql
│       ├── 02_trade_logs.sql
│       ├── 05_fundamental_chips.sql
│       ├── 06_macro_sentiment.sql
│       ├── 07_recommendations.sql
│       └── 08_enhanced_strategy_schema.sql
│
├── doc/
│   ├── AGENTS.md
│   ├── CLAUDE.md
│   ├── LOCAL_SIMULATION_GUIDE.md
│   ├── ML_PLATFORM_GUIDE.md
│   ├── updatelist.md
│   └── WORKSPACE_SCAN_REPORT.md      # ← This file
│
├── openspec/                         # Project specs & change logs
│   ├── AGENTS.md
│   ├── project.md
│   ├── changes/                      # ~15 change directories
│   ├── specs/
│   └── switch-to-local-simulation/
│
├── scripts/                          # Top-level utility scripts
│   ├── migrate_secrets_to_env.py
│   ├── populate_backtest_data.py
│   ├── populate_mock_macro.py
│   ├── populate_sector_momentum.py
│   ├── run_oneclick_regression.ps1
│   └── setup_rich_menu.py
│
├── strategies/                       # Strategy Engine (Docker service)
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── train_model.py                # Top-level model training entry
│   ├── __pycache__/                  # ⚠ ORPHANED (no .py siblings need it)
│   │   └── train_model.cpython-311.pyc
│   ├── data/                         # ML model artifacts
│   │   ├── combined_model.pkl
│   │   ├── feature_importance.png
│   │   └── (per-symbol .pkl files)
│   ├── scripts/
│   │   ├── __pycache__/
│   │   ├── ingest_full_data.py
│   │   ├── run_daily_screener.py
│   │   ├── run_ml_backtest_2024.py
│   │   ├── run_screener_backtest.py
│   │   └── train_local_model.py
??  ??  ????? manual_checks/
??  ??      ????? line_push.py
??  ??      ????? live_screening.py
│   ├── src/                          # Main source package
│   │   ├── __pycache__/
│   │   ├── config.py                 # (222 lines) Shared constants & helpers
│   │   ├── main.py                   # (526 lines) Entry point, scheduler
│   │   ├── adapters/
│   │   │   ├── __init__.py
│   │   │   ├── __pycache__/
│   │   │   ├── broker.py             # (722 lines) AlpacaBroker, MockBroker
│   │   │   ├── database.py           # (407 lines) DatabaseAdapter
│   │   │   ├── market_data.py        # (304 lines) yfinance wrappers
│   │   │   └── notifier.py           # (371 lines) LineNotifier
│   │   ├── core/
│   │   │   ├── __init__.py
│   │   │   ├── __pycache__/
│   │   │   ├── backtest.py           # (290 lines) VectorBT backtest
│   │   │   ├── position_sizing.py    # ATR-based position sizing
│   │   │   └── risk_manager.py       # Portfolio risk management
│   │   ├── ml/
│   │   │   ├── __init__.py
│   │   │   ├── __pycache__/
│   │   │   ├── features.py           # (554 lines) Feature engineering
│   │   │   └── model.py              # (602 lines) XGBoost/RF model
│   │   ├── screener/
│   │   │   ├── __init__.py
│   │   │   ├── __pycache__/
│   │   │   ├── engine.py             # (496 lines) DailyScreener
│   │   │   └── support_resistance.py # SMA/ATR support-resistance
│   │   ├── strategies/
│   │   │   ├── __init__.py           # Re-exports all strategies
│   │   │   ├── __pycache__/
│   │   │   ├── registry.py           # BaseScreenStrategy ABC + registry
│   │   │   ├── momentum.py           # (235 lines) Breakout, Acceleration
│   │   │   ├── fundamental.py        # PEG, DuPont
│   │   │   ├── institutional.py      # Institutional ownership
│   │   │   ├── volume_analysis.py    # OBV, MFI, CMF
│   │   │   ├── enhanced_momentum.py  # Multi-TF Momentum, Relative Strength
│   │   │   ├── earnings_quality.py   # Earnings quality screen
│   │   │   ├── sector.py             # Sector rotation
│   │   │   ├── macro_filter.py       # Macro regime classification
│   │   │   ├── ml_strategy.py        # (388 lines) MLStrategy wrapper
│   │   │   └── value.py              # Value strategy
│   │   └── utils/
│   │       ├── __init__.py
│   │       ├── __pycache__/
│   │       ├── db.py                 # DB config & engine
│   │       └── security.py           # Secret management
│   └── tests/
│       ├── test_strategies.py        # 9 test classes
│       ├── test_macro_and_sector.py
│       └── test_position_and_risk.py
│
└── web/                              # Web Dashboard (Docker service)
    ├── Dockerfile
    ├── requirements.txt
    ├── __pycache__/
    ├── app.py                        # (872 lines) Flask app, API routes
    ├── db.py                         # DB config + schema helpers
    ├── security.py                   # Secret management
    ├── bot/
    │   ├── __init__.py
    │   ├── __pycache__/
    │   └── handler.py                # (1013 lines) Line Bot commands
    ├── static/
    │   └── style.css
    └── templates/
        └── index.html
```

---

## 2. All Python Files with Key Functions & Classes

### strategies/src/config.py (222 lines)
| Type | Name | Description |
|------|------|-------------|
| const | `DEFAULT_SYMBOLS` | 51 US stock tickers |
| const | `BACKTEST_SYMBOLS` | 30 backtesting tickers |
| func | `calc_rsi(series, period=14)` | RSI calculation |
| func | `calc_atr(df, period=14)` | ATR calculation |
| func | `calc_rule_score(r_breakout, r_accel, r_peg, r_dupont)` | Weighted composite score |
| func | `evaluate_stock_rules(df, info)` | **⚠ DEPRECATED** — still present |
| func | `evaluate_stock_rules_v2(df, info, symbol)` | Multi-strategy evaluation |
| func | `_import_all_strategies()` | Dynamic strategy import |

### strategies/src/main.py (526 lines)
| Type | Name | Description |
|------|------|-------------|
| func | `execute_trades(broker, target_positions, db)` | Execute trade signals |
| func | `job()` | Main scheduled job |
| func | `run_scheduler()` | APScheduler cron setup |
| func | `main()` | Entry point |
| const | `TRADING_MODE` | `backtest` / `paper` / `simulation` |
| const | `STRATEGY_TYPE` | `traditional` / `ml` / `screener` |

### strategies/src/adapters/broker.py (722 lines)
| Type | Name | Description |
|------|------|-------------|
| class | `AlpacaBroker` | Paper trading via Alpaca API |
| class | `MockBroker` | Local simulation with JSON state + MySQL logging |
| method | `.get_account()` | Account balance/equity |
| method | `.get_positions()` | Current positions |
| method | `.submit_order()` | Place buy/sell order |
| method | `.check_risk()` | Pre-trade risk check |
| method | `.close_position()` | Close specific position |

### strategies/src/adapters/database.py (407 lines)
| Type | Name | Description |
|------|------|-------------|
| class | `DatabaseAdapter` | MySQL via SQLAlchemy |
| method | `.save_market_data()` | Persist OHLCV data |
| method | `.save_backtest_run()` | Persist backtest results |
| method | `.get_market_data()` | Retrieve price data |
| method | `.save_fundamentals()` | Persist fundamental data |
| method | `.get_macro_data()` | Retrieve macro indicators |
| method | `.get_fundamental_data()` | Retrieve fundamental data |

### strategies/src/adapters/market_data.py (304 lines)
| Type | Name | Description |
|------|------|-------------|
| func | `fetch_data(symbol, period, interval)` | Single stock data via yfinance |
| func | `fetch_fundamentals(symbol)` | Stock fundamentals |
| func | `download_and_save(symbols, period, interval)` | Batch download + DB persist |
| func | `fetch_multiple(symbols, period, interval)` | Batch fetch (parallel) |
| func | `get_latest_price(symbol)` | Current price |
| func | `fetch_macro_data(indicator)` | Macro indicator data |

### strategies/src/adapters/notifier.py (371 lines)
| Type | Name | Description |
|------|------|-------------|
| class | `LineNotifier` | LINE Messaging API integration |
| method | `.send_text()` | Push text message |
| method | `.send_signal()` | Push trade signal |
| method | `.send_daily_summary()` | Push daily report |
| method | `.send_error_alert()` | Push error notification |
| method | `.send_flex_report()` | Push Flex Message |
| method | `._build_stock_bubble()` | Build Flex bubble (⚠ duplicated in handler.py) |
| func | `get_notifier()` | Singleton factory |
| func | `send_signal()` | Module-level convenience wrapper |

### strategies/src/core/backtest.py (290 lines)
| Type | Name | Description |
|------|------|-------------|
| func | `run_sma_strategy()` | SMA crossover via VectorBT |
| func | `print_performance_report()` | Console report |
| func | `calculate_metrics()` | Return/Sharpe/drawdown metrics |
| func | `calculate_atr()` | ⚠ Wrapper → `config.calc_atr()` |
| func | `apply_atr_stop()` | ATR-based stop loss |
| func | `calculate_atr_stop_levels()` | Support/resistance from ATR |
| func | `run_strategy_with_atr_stop()` | Strategy with ATR stop |

### strategies/src/core/position_sizing.py
| Type | Name | Description |
|------|------|-------------|
| func | `calc_atr_position_size()` | ATR-based position sizing |
| func | `calc_equal_risk_weights()` | Equal-risk portfolio weights |
| func | `calc_atr_from_df()` | ATR from DataFrame |

### strategies/src/core/risk_manager.py
| Type | Name | Description |
|------|------|-------------|
| class | `PositionRisk` | Dataclass for position risk data |
| class | `RiskManager` | Portfolio-level risk management |
| method | `.add_position()` | Track new position |
| method | `.remove_position()` | Remove closed position |
| method | `.check_all()` | Check all risk limits |
| method | `.get_status()` | Portfolio risk summary |

### strategies/src/ml/features.py (554 lines)
| Type | Name | Description |
|------|------|-------------|
| func | `calculate_rsi()` | ⚠ Wrapper → `config.calc_rsi()` |
| func | `calculate_macd()` | MACD indicator |
| func | `calculate_sma_diff()` | SMA difference |
| func | `calculate_volatility()` | Historical volatility |
| func | `calculate_momentum()` | Price momentum |
| func | `calculate_distance_from_ma()` | Distance from moving average |
| func | `calculate_52week_high_distance()` | Distance from 52-week high |
| func | `calculate_volume_volatility()` | Volume volatility |
| func | `_fetch_spy_close()` | SPY benchmark data |
| func | `calculate_relative_strength_spy()` | Relative strength vs SPY |
| func | `calculate_volume_price_trend()` | Volume-price trend |
| func | `make_features()` | Master feature builder |
| func | `get_feature_columns()` | Feature column list |
| func | `prepare_train_test_split()` | Train/test data split |

### strategies/src/ml/model.py (602 lines)
| Type | Name | Description |
|------|------|-------------|
| class | `StrategyModel` | XGBoost + RandomForest ML model |
| method | `.train()` | Train classifier |
| method | `.predict()` | Binary prediction |
| method | `.predict_proba()` | Probability prediction |
| method | `.get_prediction_confidence()` | Confidence score |
| method | `.save()` / `.load()` | Pickle model persistence |
| method | `.get_feature_importance()` | Feature importance ranking |
| method | `.generate_report()` | Performance metrics report |

### strategies/src/screener/engine.py (496 lines)
| Type | Name | Description |
|------|------|-------------|
| class | `DailyScreener` | Daily stock screening engine |
| method | `._init_ml()` | Initialize ML model |
| method | `._predict_ml()` | ML prediction |
| method | `.fetch_stock_data()` | Fetch stock data |
| method | `.evaluate_stock()` | Evaluate single stock |
| method | `.scan_all()` | Scan all symbols |
| method | `.get_top_recommendations()` | Top-N picks |
| method | `.save_to_db()` | Persist results |

### strategies/src/screener/support_resistance.py
| Type | Name | Description |
|------|------|-------------|
| func | `calc_support_resistance(df)` | SMA + ATR band support/resistance |

### strategies/src/strategies/registry.py
| Type | Name | Description |
|------|------|-------------|
| class | `BaseScreenStrategy` | ABC with auto-registration via `__init_subclass__` |
| func | `get_all_strategies()` | List registered strategies |
| func | `get_strategies_by_category()` | Filter by category |
| func | `evaluate_all_strategies()` | Run all registered screens |
| func | `calc_composite_score()` | Weighted composite score |

### strategies/src/strategies/momentum.py (235 lines)
| Type | Name | Description |
|------|------|-------------|
| func | `screen_breakout(df)` | Breakout detection |
| func | `screen_acceleration(df, n=20)` | Momentum acceleration |
| func | `run_momentum_strategy(data, lookback_period=200)` | Full momentum strategy |
| class | `BreakoutStrategy` | Registry-registered |
| class | `AccelerationStrategy` | Registry-registered |

### strategies/src/strategies/fundamental.py
| Type | Name | Description |
|------|------|-------------|
| func | `screen_peg(info)` | PEG ratio screen |
| func | `screen_dupont(info)` | DuPont analysis screen |
| class | `PEGStrategy` / `DuPontStrategy` | Registry-registered |

### strategies/src/strategies/institutional.py
| Type | Name | Description |
|------|------|-------------|
| func | `screen_institutional(info)` | Institutional ownership screen |
| class | `InstitutionalStrategy` | Registry-registered |

### strategies/src/strategies/volume_analysis.py
| Type | Name | Description |
|------|------|-------------|
| func | `calc_obv()`, `calc_mfi()`, `calc_cmf()` | Volume indicators |
| func | `screen_volume_structure(df)` | Volume structure screen |
| func | `screen_money_flow(df)` | Money flow screen |
| class | `VolumeStructureStrategy` / `MoneyFlowStrategy` | Registry-registered |

### strategies/src/strategies/enhanced_momentum.py
| Type | Name | Description |
|------|------|-------------|
| func | `screen_multi_tf_momentum(df)` | Multi-timeframe momentum |
| func | `screen_relative_strength(df)` | Relative strength screen |
| class | `MultiTFMomentumStrategy` / `RelativeStrengthStrategy` | Registry-registered |

### strategies/src/strategies/earnings_quality.py
| Type | Name | Description |
|------|------|-------------|
| func | `screen_earnings_quality(info)` | Earnings quality screen |
| class | `EarningsQualityStrategy` | Registry-registered |

### strategies/src/strategies/sector.py
| Type | Name | Description |
|------|------|-------------|
| const | `SECTOR_MAP`, `SECTOR_ETF` | Sector → ETF mappings |
| func | `get_sector()` | Get stock sector |
| func | `screen_sector_rotation()` | Sector rotation screen |
| func | `apply_sector_constraint()` | Portfolio sector limits |
| class | `SectorRotationStrategy` | Registry-registered |

### strategies/src/strategies/macro_filter.py
| Type | Name | Description |
|------|------|-------------|
| class | `MacroRegime` | IntEnum: RISK_ON, NEUTRAL, RISK_OFF |
| func | `classify_macro_regime()` | Classify current regime |
| func | `get_regime_strategy_filter()` | Strategy filter for regime |
| func | `fetch_macro_indicators_from_db()` | DB macro data fetch |

### strategies/src/strategies/ml_strategy.py (388 lines)
| Type | Name | Description |
|------|------|-------------|
| class | `MLStrategy` | ML-based signal generation |
| method | `.generate_signal()` | Generate buy/sell signal |
| method | `.scan_multiple_symbols()` | Batch symbol scanning |
| method | `._get_price_data()` | Fetch price data |
| method | `._get_macro_data()` | Fetch macro data |
| method | `._get_fundamental_data()` | Fetch fundamental data |

### strategies/src/strategies/value.py
| Type | Name | Description |
|------|------|-------------|
| func | `run_value_strategy()` | Value investing strategy |
| func | `run_multi_symbol_value()` | Multi-symbol value scan |

### strategies/src/utils/db.py
| Type | Name | Description |
|------|------|-------------|
| func | `get_db_config()` | ⚠ Duplicate of web/db.py |
| func | `build_connection_string()` | ⚠ Duplicate of web/db.py |
| func | `get_engine()` | ⚠ Duplicate of web/db.py |

### strategies/src/utils/security.py (139 lines)
| Type | Name | Description |
|------|------|-------------|
| func | `get_secret()` | ⚠ Duplicate of web/security.py (different behavior!) |
| func | `require_secret()` | Raises if secret missing |
| func | `is_production()` | Docker detection |
| func | `is_simulation_mode()` | Simulation mode check |
| func | `require_secret_if_not_simulation()` | Conditional requirement |

### web/app.py (872 lines)
| Type | Name | Description |
|------|------|-------------|
| route | `/` | Dashboard index |
| route | `/health` | Health check |
| route | `/api/strategies` | Strategy list |
| route | `/api/run/<id>/equity` | Backtest equity curve |
| route | `/api/run/<id>/trades` | Backtest trades |
| route | `/api/ml_status` | ML model status |
| route | `/api/recommendations` | Stock recommendations |
| route | `/api/stock/<symbol>` | Stock detail |
| route | `/api/portfolio` | Portfolio summary |
| route | `/api/macro` | Macro indicators |
| route | `/api/sectors` | Sector data |
| route | `/api/recommendations/dates` | Recommendation dates |
| auth | `HTTPBasicAuth` | Admin password via get_secret |

### web/db.py (110 lines)
| Type | Name | Description |
|------|------|-------------|
| func | `get_db_config()` | ⚠ Duplicate of strategies/src/utils/db.py |
| func | `build_connection_string()` | ⚠ Duplicate of strategies/src/utils/db.py |
| func | `get_engine()` | ⚠ Duplicate of strategies/src/utils/db.py |
| func | `table_exists()` | ⚠ **DEFINED TWICE** in same file (lines ~62 and ~92) |
| func | `column_exists()` | ⚠ **DEFINED TWICE** in same file (lines ~72 and ~102) |

### web/security.py (77 lines)
| Type | Name | Description |
|------|------|-------------|
| func | `get_secret()` | ⚠ Duplicate of strategies version — **blocks env vars if /run/secrets exists** |
| func | `is_production()` | Docker detection |

### web/bot/handler.py (1013 lines)
| Type | Name | Description |
|------|------|-------------|
| blueprint | `line_bot_bp` | Flask Blueprint |
| decorator | `verify_signature` | HMAC-SHA256 validation |
| route | `/callback` | Webhook handler (GET+POST) |
| route | `/webhook/info` | Webhook status |
| func | `process_command()` | Command dispatcher |
| func | `_cmd_top5()` | Top 5 recommendations |
| func | `_cmd_top5_basic()` | Basic top 5 |
| func | `_cmd_ml()` | ML status |
| func | `_cmd_stock()` | Stock lookup |
| func | `_cmd_market()` | Market overview |
| func | `_cmd_history()` | History query |
| func | `_cmd_sector()` | Sector info |
| func | `_cmd_status()` | System status |
| func | `_build_top5_flex()` | Flex message builder |
| func | `_build_bubble()` | ⚠ Similar to notifier._build_stock_bubble() |
| func | `_flex_kv()` | ⚠ Similar to notifier's Flex helpers |
| func | `reply_messages()` | HTTP reply to LINE |

### strategies/train_model.py
| Type | Name | Description |
|------|------|-------------|
| func | `load_data_from_db()` | Load training data from DB |
| func | `train_model_for_symbol()` | Per-symbol model training |
| func | `train_combined_model()` | Combined multi-symbol model |
| func | `main()` | Entry point |

### strategies/scripts/ingest_full_data.py
| Type | Name | Description |
|------|------|-------------|
| class | `DataIngestion` | Full data ingestion pipeline |
| func | `main()` | Entry point |

### strategies/scripts/run_daily_screener.py
| Type | Name | Description |
|------|------|-------------|
| func | `print_report()` | Console report |
| func | `main()` | Entry point |

### strategies/scripts/run_ml_backtest_2024.py
| Type | Name | Description |
|------|------|-------------|
| func | `fetch_yfinance()` | yfinance data fetch |
| func | `fetch_yfinance_fundamentals()` | Fundamentals fetch |
| func | `run_walk_forward()` | Walk-forward backtest |
| func | `fetch_spy_benchmark()` | SPY benchmark |
| func | `plot_equity()` | Equity curve plot |
| func | `main()` | Entry point |

### strategies/scripts/run_screener_backtest.py
| Type | Name | Description |
|------|------|-------------|
| func | `fetch_all_history()` | Batch historical data |
| func | `fetch_fundamentals()` | Batch fundamentals |
| func | `evaluate_at_date()` | Point-in-time evaluation |
| func | `run_backtest()` | Full backtest loop |
| func | `main()` | Entry point |

### strategies/scripts/train_local_model.py
| Type | Name | Description |
|------|------|-------------|
| func | `main()` | Entry point (local model training) |

### scripts/setup_rich_menu.py
| Type | Name | Description |
|------|------|-------------|
| func | `create_rich_menu()` | Create LINE Rich Menu |
| func | `upload_image()` | Upload Rich Menu image |
| func | `set_default()` | Set default Rich Menu |
| func | `main()` | Entry point |

### scripts/populate_sector_momentum.py
| Type | Name | Description |
|------|------|-------------|
| func | `populate_sector_momentum()` | Insert mock sector data |
| func | `main()` | Entry point |

### scripts/populate_mock_macro.py
| Type | Name | Description |
|------|------|-------------|
| func | `populate()` | Insert mock macro data |
| func | `main()` | Entry point |

### scripts/populate_backtest_data.py
| Type | Name | Description |
|------|------|-------------|
| func | `create_sample_backtest_data()` | Insert sample backtest data |
| func | `main()` | Entry point |

### scripts/migrate_secrets_to_env.py
| Type | Name | Description |
|------|------|-------------|
| func | `migrate_secrets_to_env()` | Migrate Docker secrets → .env |

### strategies/tests/ (5 test files)
| File | Contents |
|------|----------|
| `test_strategies.py` | 9 test classes covering all strategy screens |
| `test_macro_and_sector.py` | Macro/sector test |
| `test_position_and_risk.py` | Position sizing/risk test |

---

## 3. Duplicate Function Definitions

### 🔴 Critical: Same-file duplicates

| File | Function | Issue |
|------|----------|-------|
| `web/db.py` | `table_exists()` | **Defined TWICE** (lines ~62 and ~92) — exact same logic, second overwrites first |
| `web/db.py` | `column_exists()` | **Defined TWICE** (lines ~72 and ~102) — exact same logic, second overwrites first |

### 🟠 High: Cross-service duplicates (different behavior!)

| Function | File A | File B | Difference |
|----------|--------|--------|------------|
| `get_secret()` | `strategies/src/utils/security.py` | `web/security.py` | **Web version blocks env var fallback when `/run/secrets` exists; strategies version always falls through to env vars** |

### 🟡 Medium: Cross-service duplicates (identical logic)

| Function | File A | File B |
|----------|--------|--------|
| `get_db_config()` | `strategies/src/utils/db.py` | `web/db.py` |
| `build_connection_string()` | `strategies/src/utils/db.py` | `web/db.py` |
| `get_engine()` | `strategies/src/utils/db.py` | `web/db.py` |
| `is_production()` | `strategies/src/utils/security.py` | `web/security.py` |

### 🟢 Low: Intentional backward-compat wrappers

| Wrapper | Location | Delegates To |
|---------|----------|-------------|
| `calculate_rsi()` | `ml/features.py` | `config.calc_rsi()` |
| `calculate_atr()` | `core/backtest.py` | `config.calc_atr()` |

### 🟡 Medium: Duplicated Flex Message logic

| Function | Location A | Location B |
|----------|-----------|-----------|
| `_build_stock_bubble()` / `_build_bubble()` | `adapters/notifier.py` | `web/bot/handler.py` |
| `_flex_kv()` | `adapters/notifier.py` | `web/bot/handler.py` |

### 🟡 Medium: Duplicated constants

| Constant | Location A | Location B |
|----------|-----------|-----------|
| `SECTOR_MAP` | `strategies/src/strategies/sector.py` | Hardcoded subsets in `web/bot/handler.py` and `web/app.py` |

### 🟡 Medium: Deprecated code still present

| Item | Location | Note |
|------|----------|------|
| `evaluate_stock_rules()` | `strategies/src/config.py` | Marked deprecated; `evaluate_stock_rules_v2()` is the replacement |

---

## 4. Redundant / Unnecessary Files

| File/Directory | Issue | Recommendation |
|----------------|-------|----------------|
| `strategies/__pycache__/` | Orphaned cache; `train_model.py` exists but this cache serves no runtime purpose in the repo | Delete directory |
| All 11 `__pycache__/` dirs | Should be git-ignored, not committed | Verify `.gitignore` covers `**/__pycache__/` |
| `web/db.py` lines 87-110 | Exact duplicate of `table_exists()` + `column_exists()` at lines 57-80 | **Remove the second block** |
| `config.evaluate_stock_rules()` | Deprecated, replaced by `evaluate_stock_rules_v2()` | Remove after confirming no callers |

---

## 5. Import Dependency Map

### strategies/src/ — Internal Dependencies

```
main.py
  ├── adapters.market_data  (download_and_save, fetch_data)
  ├── adapters.database     (DatabaseAdapter)
  ├── adapters.notifier     (send_signal, get_notifier)
  ├── adapters.broker       (AlpacaBroker, MockBroker)
  ├── strategies            (run_momentum_strategy, run_value_strategy)
  └── config                (DEFAULT_SYMBOLS)

adapters/
  broker.py        → utils.security (require_secret, get_secret)
  database.py      → utils.db (get_db_config, get_engine)
  market_data.py   → adapters.database (DatabaseAdapter)
  notifier.py      → utils.security (get_secret)

core/
  backtest.py      → config (calc_atr)
  position_sizing.py → (no internal deps)
  risk_manager.py    → (no internal deps)

ml/
  features.py      → config (calc_rsi)
  model.py         → (no internal deps, uses sklearn/xgboost)

screener/
  engine.py        → config (DEFAULT_SYMBOLS, evaluate_stock_rules_v2)
                   → screener.support_resistance (calc_support_resistance)
  support_resistance.py → config (calc_atr)

strategies/
  momentum.py      → config (calc_rsi)
  ml_strategy.py   → adapters.database (DatabaseAdapter)
                   → adapters.market_data (fetch_data)
                   → ml.features (make_features, get_feature_columns)
                   → ml.model (StrategyModel)
  registry.py      → (no internal deps)
  fundamental.py   → (no internal deps)
  institutional.py → (no internal deps)
  volume_analysis.py → (no internal deps)
  enhanced_momentum.py → (no internal deps)
  earnings_quality.py  → (no internal deps)
  sector.py        → (no internal deps)
  macro_filter.py  → (no internal deps)
  value.py         → (no internal deps)

utils/
  db.py            → utils.security (get_secret)
  security.py      → (no internal deps)
```

### web/ — Internal Dependencies

```
app.py
  ├── security  (get_secret)
  ├── bot       (line_bot_bp)
  └── db        (get_db_config, get_engine, table_exists, column_exists)

bot/handler.py
  ├── security  (get_secret)
  └── db        (get_engine, table_exists, column_exists)

db.py
  └── security  (get_secret)

security.py → (no internal deps)
```

### Cross-Service Dependency Diagram

```
┌──────────────────────────────────┐    ┌──────────────────────────────┐
│         strategies/src/          │    │           web/               │
│                                  │    │                              │
│  utils/security.py ◄──┐         │    │  security.py ◄──┐           │
│  utils/db.py ◄────────┤         │    │  db.py ◄────────┤           │
│                        │         │    │                  │           │
│  adapters/broker.py ───┘         │    │  app.py ─────────┘           │
│  adapters/database.py ─┘         │    │  bot/handler.py ─┘           │
│  adapters/notifier.py ─┘         │    │                              │
│                                  │    │                              │
│  ⚠ No cross-imports between     │    │  ⚠ No cross-imports between  │
│    strategies/ and web/          │    │    web/ and strategies/      │
└──────────────────────────────────┘    └──────────────────────────────┘
         │                                         │
         └─── Both use MySQL (usstock) ────────────┘
         └─── Both use Docker Secrets ─────────────┘
         └─── Both duplicate db.py, security.py ───┘
```

### External Dependencies (key packages)

| Package | Used By |
|---------|---------|
| `yfinance` | `adapters/market_data.py`, `screener/engine.py`, scripts |
| `sqlalchemy` + `mysql-connector-python` | `utils/db.py`, `web/db.py`, `adapters/database.py` |
| `xgboost` | `ml/model.py` |
| `sklearn` | `ml/model.py` |
| `vectorbt` | `core/backtest.py` |
| `pandas` / `numpy` | Almost everywhere |
| `flask` + `flask_httpauth` | `web/app.py` |
| `apscheduler` | `main.py` |
| `requests` | `adapters/notifier.py`, `web/bot/handler.py` |

---

## 6. Summary of Findings

### Architecture
- **Two Docker services** (`strategies/` and `web/`) sharing the same MySQL database but with **no shared Python code** — leading to duplicated utility modules.
- **Strategy Registry Pattern** uses ABC auto-registration; 12 strategy classes registered across 8 files.
- **ML Pipeline**: Feature engineering → XGBoost/RF model → predictions, with walk-forward backtesting.
- **LINE Bot** has a command-based interface with Flex Message responses.

### Top Issues to Address

1. **`web/db.py` has `table_exists()` and `column_exists()` defined TWICE each** — second definition silently overwrites first. Remove the duplicate block (lines 87-110).

2. **`get_secret()` behavioral divergence** — The web version is more secure (blocks env fallback in production) while the strategies version always allows env fallback. This could cause **security issues in production**. Recommend unifying behavior.

3. **`get_db_config()` / `build_connection_string()` / `get_engine()` duplicated** across services — Consider extracting a shared `common/` package or accepting the duplication as intentional for Docker isolation.

4. **Flex Message builders duplicated** between `notifier.py` and `handler.py` — Could share a common Flex template builder.

5. **Deprecated `evaluate_stock_rules()` still present** — Verify no callers remain, then remove.

6. **11 `__pycache__/` directories** in the repo — Ensure `.gitignore` covers them.
