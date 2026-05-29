# Screener Ops Runtime

## Docker Services

- `web`: Flask Dashboard, API routes, and LineBot webhook blueprint. The LINE webhook route is `/callback`.
- `strategies`: strategy and screener runtime code. If `USE_SCHEDULER=true`, this is the expected scheduler owner unless Docker Compose defines a dedicated scheduler service.
- `mysql`: MySQL database used by Dashboard, screener recommendations, provider health, performance, calibration, drift, and market data.

Useful commands:

```powershell
docker compose ps
docker compose logs -f web
docker compose logs -f strategies
docker compose logs -f mysql
```

## Local `.venv` Startup

```powershell
.venv/Scripts/python.exe web/app.py
```

Check runtime state:

```powershell
curl http://localhost:8000/api/ops/runtime
curl http://localhost:8000/api/ops/scheduler
```

## Market Data Pull

Manual pull:

```powershell
.venv/Scripts/python.exe scripts/pull_market_data.py --symbols AAPL,MSFT,NVDA
```

Dry run:

```powershell
.venv/Scripts/python.exe scripts/pull_market_data.py --symbols AAPL,MSFT,NVDA --dry-run
```

The pull uses the screener provider chain, updates `market_data` through `DatabaseAdapter.save_market_data()`, and records status in `market_data_pull_log`.

## Provider Smoke

Live provider-chain smoke:

```powershell
.venv/Scripts/python.exe scripts/smoke_live_provider_chain.py --symbols AAPL,MSFT,NVDA --days 90
```

The smoke command prints provider attempts, fallback attempts, coverage, effective provider, top error types, skip reasons, and next operator action. It does not write recommendations.

## Webhook Test

The LineBot webhook is handled by the `web` service at `/callback`. For local validation, confirm the app is reachable and inspect logs:

```powershell
curl http://localhost:8000/health
docker compose logs -f web
```

## Common Failures

- OpenBB parse errors: run provider smoke, inspect `/api/provider-health/latest`, and verify yfinance/local DB fallback.
- Critical zero coverage: run `scripts/pull_market_data.py`, inspect `market_data_pull_log`, and confirm local DB fallback age.
- Scheduler unknown: inspect `/api/ops/scheduler`; if it reports no scheduler, verify `USE_SCHEDULER` and Docker service ownership.
- LineBot unavailable: verify `LINE_CHANNEL_ACCESS_TOKEN`/`LINE_CHANNEL_SECRET` are configured and check `web` logs.
