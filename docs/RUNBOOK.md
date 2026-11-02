# PSX Research Lab — Operational Runbook

## 1. Routine Verification & CLI Commands
- `bash scripts/doctor.sh`: Verify toolchain, dependencies, environment, repository visibility, and zero-cost posture.
- `pnpm test`: Run full TypeScript Vitest suite (`packages/shared`, `apps/api`, `apps/web`).
- `pytest services/collector`: Run full Python collector suite with coverage.
- Inspect market session:
  ```bash
  python -m services.collector.src.collector.cli calendar
  ```
- Inspect persistent 24h budget and active runner lease:
  ```bash
  python -m services.collector.src.collector.cli budget
  ```
- Run a dry-run collection cycle:
  ```bash
  python -m services.collector.src.collector.cli run --dry-run
  ```
- Run a forced collection cycle (bypasses out-of-market-hours calendar check):
  ```bash
  python -m services.collector.src.collector.cli run --force
  ```

## 2. Handling Upstream 429 / 503 Cooldown
1. When an upstream error occurs, `CooldownManager` records the timestamp and sets `cooldown_until`.
2. Inspect cooldown status:
   ```bash
   cat ~/.psx_cooldown_state.json
   ```
3. To view current 24-hour request count and runner lease:
   ```bash
   python -m services.collector.src.collector.cli budget
   ```
4. Never rotate IP proxies or bypass cooldowns. Wait for the cooldown window to elapse.

## 3. Investigating Stale Data Badge
If the terminal UI displays `STALE DATA (LAST GOOD: YYYY-MM-DD HH:MM PKT)`:
1. Check GitHub Actions collector workflow runs:
   ```bash
   gh run list --workflow=collector.yml
   ```
2. Verify if GitHub Actions scheduled runs were delayed by GitHub runner queues.
3. Check Healthchecks.io ping status for failure reasons.
4. If a scheduled run was skipped or failed, trigger a manual dispatch:
   ```bash
   gh workflow run collector.yml -f force=true
   ```

## 4. Disaster Recovery & Offline Mode
If PSX upstream is completely unreachable:
- Terminal continues serving the latest accepted snapshot from Cloudflare D1/KV.
- Backtesting engine continues to operate offline in the browser using cached and historical datasets.
- Gemini AI strategy compilation remains available as long as application quota allows.
