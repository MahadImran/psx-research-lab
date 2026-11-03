# PSX Research Lab — Delivery Roadmap

## Milestone Overview

### M0: Repository, Monorepo Scaffolding, and Cloud Architecture (AWAITING OWNER ACCEPTANCE)
- [x] Dual-repository boundary: Public application repository (`MahadImran/psx-research-lab`) and strictly private raw data archive (`MahadImran/psx-research-data`).
- [x] Monorepo structure: `apps/web`, `apps/api`, `services/collector`, `packages/shared`, `docs`.
- [x] Comprehensive architectural contracts: `ARCHITECTURE.md`, `ADRS.md`, `DATA_CONTRACT.md`, `FOUNDATION_RISK_REGISTER.md`, `RUNBOOK.md`, `COST_LIMITS.md`, `SETUP.md`, `THREAT_MODEL.md`.
- [x] Zero-dollar posture verification: GitHub Actions minute budgets, Cloudflare Workers Free limits, Gemini free tier constraints.
- [x] Supply-chain pinning: Strict dependency pinning, vendor isolation, Node 24 / pnpm 10 and Python 3.11/3.14 compatibility.
- [x] Acceptance sign-off: `docs/M0_ACCEPTANCE.md` (Awaiting Owner Acceptance).

### M1: Source Adapter Abstraction & Bounded PSX Probe (AWAITING OWNER ACCEPTANCE)
- [x] Python source adapter abstraction (`PSXSourceAdapter`, `PSXDPSAdapter`, `FixtureAdapter`).
- [x] Upstream 250 requests/24h rolling budget fuse and fail-closed mechanism.
- [x] HTTP 429/503 circuit breaker with Retry-After header parsing and exponential backoff.
- [x] Dynamic session token and cookie negotiation (`PSXTokenProvider`).
- [x] Defensive HTML table fragment parsing (`table_records`).
- [x] Market trading calendar (`MarketCalendar`): Karachi timezone (UTC+5), regular vs Friday split sessions, public holidays.
- [x] Bounded read-only probe verified live on GitHub-hosted Linux runner.
- [x] Acceptance sign-off: `docs/M1_ACCEPTANCE.md` (Awaiting Owner Acceptance).

### M2: Persistent Concurrency, Durable Archiving, & Remediation (AWAITING OWNER ACCEPTANCE)
- [x] Distributed lease coordination (`PersistentCoordinator`) with 15-minute TTL and optimistic concurrency (HTTP 409 retry loop with jitter).
- [x] Remote request pre-reservation: Commits quota reservation remotely before opening outbound network sockets; survives runner crashes.
- [x] Durable private archival (`DurableArchiveManager`): Level 9 gzip compression sharded by `raw/YYYY/MM/DD/` committed to private repository.
- [x] Raw archive object immutability: Rejection of conflicting content at existing raw paths (`ArchiveCommitError`).
- [x] Cumulative daily SHA-256 integrity manifest generation (`manifests/YYYY-MM-DD.json`) merging files across all daily cycles without erasing earlier runs; Cycle 1 explicitly recorded.
- [x] Corrupt manifest quarantine: Malformed manifests fail closed and preserve corrupted bytes for forensics.
- [x] Cryptographic readback verification: Remote commits validated by immediate GET and SHA-256 check with replication lag tolerance.
- [x] Durable snapshot deduplication: Tracking `{source}:{trading_date}` SHA-256 hashes to prevent redundant archives.
- [x] Fail-closed Cloudflare Access edge authentication: Defaulting to `requireAccess !== false`.
- [x] Atomic SQLite replay lock in Cloudflare D1 (`seen_nonces`) eliminating check-then-act race conditions; removal of KV-only fallback.
- [x] Two-phase D1 staging and publication protocol (`is_active = 0` during staging, `is_active = 1` upon atomic publication).
- [x] Multi-tier Data Quality Grades (`GRADE_A`, `GRADE_B`, `GRADE_C`, `QUARANTINE`) with strict candle geometry enforcement.
- [x] Granular status reporting (`SUCCESS`, `DATA_UNCHANGED`, `ARCHIVE_COMMITTED_INGEST_PENDING`, `ARCHIVE_FAILED`, `INGEST_FAILED`, `MARKET_CLOSED`).
- [x] Adversarial chaos test suite (`test_adversarial_failures.py`) with 8 passing scenarios; 71 Python tests passing; 19 TypeScript tests passing.
- [x] Acceptance sign-off: `docs/M2_ACCEPTANCE.md` (Awaiting Owner Acceptance).

---

### GATEWAY: FOUNDATION LOCKDOWN DIRECTIVE
> [!IMPORTANT]
> **MILESTONE 3 IS CURRENTLY NOT AUTHORIZED.**
> Milestones M0, M1, and M2 have undergone complete engineering lockdown, code refactoring, adversarial testing, and live verification. No M3 code, Cloudflare infrastructure deployment, or unattended cron scheduling may begin without explicit written authorization from the owner.

---

### M3: Cloudflare Private Serving & Independent Watchdog (GATEWAY LOCKED)
- [ ] Deploy Cloudflare D1 database schema (`apps/api/src/db/schema.sql`).
- [ ] Deploy Cloudflare Workers free-tier API (`apps/api`).
- [ ] Configure Cloudflare Access Free (Zero Trust) to restrict all staging endpoints.
- [ ] Cloudflare Cron watchdog at minute 45.
- [ ] End-to-end ingestion pipeline from GitHub collector to Cloudflare D1.
- [ ] Nightly encrypted D1 exports to private GitHub archive.

### M4: Quantitative Financial Terminal & Deterministic Backtesting (PENDING)
- [ ] High-density financial terminal UI (React + Tailwind).
- [ ] In-browser Web Worker deterministic backtesting engine.
- [ ] Golden backtesting test suites (dividends, splits, cashflows, slippage).

### M5: Gemini Conversational Research Compiler (PENDING)
- [ ] Gemini API integration with structured JSON outputs.
- [ ] Translation of natural language to versioned `ExperimentSpec` DSL.
- [ ] In-app atomic community quota limiter (50 global / 5 visitor per day).

### M6: Hardening, Fault Injection & Disaster Recovery Drills (PENDING)
- [ ] Injected missed-run test and stale data badge verification.
- [ ] Emergency whole-market snapshot fallback testing within 10ms CPU limit.
- [ ] Complete operational verification and handoff documentation.
