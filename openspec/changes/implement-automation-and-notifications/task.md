# Tasks: Automation & Line Bot Notification

This change enables fully automated operations (Cron) and real-time alerts via Line Bot, moving the system towards "set and forget".

## 1. Line Bot Integration (The Mouth)
- [x] **1.1 Line Bot Infrastructure**
    - Update `web/requirements.txt`: Ensure `line-bot-sdk` is present.
    - Create `web/bot/handler.py`: Implement webhook receiver (`/callback`).
    - **Security Check**: Verify `X-Line-Signature` to prevent spoofing.
- [x] **1.2 Push Message Logic**
    - Create `strategies/src/adapters/notifier.py`:
        - Function `send_signal(symbol, action, price, reason)`
        - Should call `web` container API or use Line SDK directly (if secrets are shared).
    - Update `main.py`: Call `notifier.send_signal()` when a new trade is generated.

## 2. Automation & Scheduling (The Heartbeat)
- [x] **2.1 Scheduler Implementation**
    - Update `strategies/requirements.txt`: Add `APScheduler`.
    - Modify `strategies/src/main.py`:
        - Wrap the main logic in a function `job()`.
        - Use `BlockingScheduler` to run `job()` every weekday at 16:15 EST (US Market Close).
- [x] **2.2 Docker Health & Restart Policy**
    - Update `docker-compose.yml`:
        - Set `restart: always` for all services.
        - Add `healthcheck` for MySQL to ensure Python waits for DB readiness.

## 3. Deployment Preparation (The Launchpad)
- [x] **3.1 Production Config**
    - Create `prod.docker-compose.yml`:
        - Remove port binding for DB (don't expose 3306 to world).
        - Use `gunicorn` instead of `flask run` for Web.
- [x] **3.2 CI/CD Scaffolding (Optional)**
    - Create `.github/workflows/deploy.yml` (Template): Automation script for future VPS deployment.

## 4. Verification
- [x] **4.1 Notification Test**
    - Create a test script to trigger a fake "BUY AAPL" message to your Line account.
- [x] **4.2 Scheduler Test**
    - Run the scheduler with a 1-minute interval to verify it triggers correctly.

---
**實施日期**: 2026-01-31
**狀態**: ✅ 全部完成