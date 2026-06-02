# Screener Architecture

## Provider Chain

`DailyScreener` uses the market data provider chain:

1. `OpenBBHistoricalProvider`
2. `YFinanceProvider`
3. `LocalDatabaseProvider`

Provider attempts are recorded with success, error type, data mode, cache age, and safe raw metadata. Coverage policy remains:

- `>= 0.60`: current recommendation write
- `0.20` to `< 0.60`: degraded/stale write when policy allows
- `< 0.20`: critical; preserve last valid recommendations when available

## Diagnostics

Provider health normalization and diagnostics live in `strategies/src/screener/market_data_resilience.py`. Live smoke and pull scripts reuse the same provider-chain path rather than issuing unrelated direct provider calls.

## Recommendation Flow

The screener writes recommendation rows with ranking metadata. `/api/recommendations` remains additive and backward-compatible. The Dashboard may hide advanced strategy flags by default, but the API keeps the complete payload.

## Performance, Calibration, And Drift

- Performance evaluation lives in `swing_performance.py`.
- Calibration profile loading and status live in `swing_calibration.py`.
- Drift monitoring, audit, backup, and rollback helpers live in `swing_calibration_drift.py`.

These modules share safe numeric formatting through `screener.presentation_utils` where practical.

## Dashboard, API, And LineBot Boundaries

- Domain calculations stay under `strategies/src/screener/`.
- Dashboard API composition stays in `web/app.py`.
- LineBot command routing and message assembly stays in `web/bot/handler.py`.
- Shared presentation and sanitization helpers live in `strategies/src/screener/presentation_utils.py`.
- Operator pull-log helpers live in `strategies/src/screener/ops_runtime.py`.

LineBot builders may sanitize presentation values, but they should not own ranking, performance, calibration, provider, or macro calculations.

## Shared Helpers

Use `presentation_utils.py` for:

- `safe_float`
- `safe_text`
- `safe_list`
- `bounded_list`
- `safe_pct_return`
- `format_metric_or_na`
- `format_status_label`
- `format_recommendation_source`
- `sanitize_for_json`
- `sanitize_for_line_flex`

Use web-local helpers only for Flask response composition or UI-specific labels. Use script-local adapters only for command-line parsing and printing.
