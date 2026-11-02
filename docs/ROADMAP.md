# PSX Research Lab — Delivery Roadmap

## Milestone Overview

### M0: Repository, Monorepo Scaffolding, and Cloud Architecture (COMPLETED)
- [x] Private monorepo structure: `apps/web`, `apps/api`, `services/collector`, `packages/shared`, `data/fixtures`, `docs`, `scripts`.
- [x] Comprehensive architectural contracts: `ARCHITECTURE.md`, `ADRS.md`, `DATA_CONTRACT.md`, `RISK_REGISTER.md`, `RUNBOOK.md`, `COST_LIMITS.md`, `SETUP.md`, `THREAT_MODEL.md`, `ROADMAP.md`.
- [x] Zero-dollar posture verification: GitHub Actions minute budgets, Cloudflare Workers Free limits, Gemini free tier constraints.
- [x] Working `doctor.sh` prerequisite checker.

### M1: Source Adapter Abstraction & Bounded PSX Probe (COMPLETED)
- [x] Python source adapter abstraction (`PSXSourceAdapter`, `PSXDPSAdapter`, `FixtureAdapter`).
- [x] Upstream 250 requests/24h rolling budget fuse and fail-closed mechanism.
- [x] HTTP 429/503 circuit breaker with Retry-After and exponential backoff.
- [x] Data sanity auditor and quarantine pipeline.
- [x] Deduplication and raw payload SHA-256 calculation.
- [x] Bounded read-only probe script (`probe.py`) covering symbols, snapshot, 2 EOD stocks, indices, and intraday.
- [x] GitHub Actions probe workflow (`probe.yml`) on hosted Ubuntu runner.

### M2: Durable Cloud Collector & Scheduled Pipelines (COMPLETED)
- [x] Market trading calendar (`MarketCalendar`): Karachi timezone (UTC+5), regular vs Friday split sessions, public holidays, EOD window.
- [x] Anti-scraping token extraction (`PSXTokenProvider`): dynamic extraction and caching of `window.__ps._k` (`X-Req-Id`).
- [x] Persistent cross-runner lease and rolling 24h 250 upstream request budget fuse (`PersistentCoordinator`).
- [x] Durable private archival (`DurableArchiveManager`): level 9 gzip compression sharded by `raw/YYYY/MM/DD/` committed to `MahadImran/psx-research-data`.
- [x] Daily SHA-256 integrity manifest generation (`manifests/YYYY-MM-DD.json`).
- [x] End-of-Day (EOD) reconciliation (`EODReconciler`): comparing preliminary quotes against `POST /historical` datewise prices.
- [x] Healthchecks.io lifecycle pings (`HealthchecksNotifier`): `/start`, `/fail`, `/skip`, and `/success` with run metrics.
- [x] Signed HMAC-SHA256 ingestion client (`IngestClient`) with Cloudflare Access service token support.
- [x] Scheduled GitHub Actions collector workflow (`.github/workflows/collector.yml`) with strict least privilege.
- [x] 100% test pass rate across 36 unit/integration tests and TypeScript suites.

### M3: Cloudflare Private Serving & Independent Watchdog (NEXT)
- [ ] Cloudflare Access Service Token integration.
- [ ] Cloudflare Cron watchdog at minute 45.
- [ ] Healthchecks.io heartbeat ping integration.
- [ ] Nightly encrypted D1 exports to private GitHub archive.
- [ ] Monthly automated cloud restore drill.

### M4: Quantitative Financial Terminal & Deterministic Backtesting
- [ ] High-density financial terminal UI (React + Tailwind).
- [ ] In-browser Web Worker deterministic backtesting engine.
- [ ] Golden backtesting test suites (dividends, splits, cashflows, slippage).

### M5: Gemini Conversational Research Compiler
- [ ] Gemini `gemini-3.5-flash-lite` integration with structured JSON outputs.
- [ ] Translation of natural language to versioned `ExperimentSpec` DSL.
- [ ] In-app atomic community quota limiter (50 global / 5 visitor per day).

### M6: Hardening, Fault Injection & Disaster Recovery Drills
- [ ] Injected missed-run test and stale data badge verification.
- [ ] Emergency whole-market snapshot fallback testing within 10ms CPU limit.
- [ ] Complete operational verification and handoff documentation.
