# PSX Research Lab — Architectural Decision Records (ADRs)

## ADR-001: Zero-Dollar Cloud-Only Hosting Topology
- **Status:** Accepted
- **Context:** The system requires scheduled automated collection, data persistence, and API serving with exactly $0 recurring spend. No Mac, Orange Pi, or local hardware should be required.
- **Decision:** Utilize GitHub Actions standard hosted Linux runners (2,000 free minutes/month) for scheduled Python collectors; Cloudflare Workers Free (100k requests/day, D1 <=5GB, KV <=1GB) for serving; Google AI Studio Gemini Free tier for conversational strategy translation.
- **Consequences:** Ephemeral runners mean state must be persisted remotely. GitHub cron can jitter or skip runs; pipeline must handle best-effort scheduling gracefully with visible staleness badges.

## ADR-002: Durable Raw Archive in Dedicated Private Repository
- **Status:** Accepted
- **Context:** Actions artifacts expire (typically 90 days) and D1 Time Travel Free provides only 7 days retention. Loss of accepted historical market data is prohibited.
- **Decision:** Maintain a dedicated private repository (`MahadImran/psx-research-data`) for immutable compressed raw JSON files (`.json.gz`), daily cumulative SHA-256 manifests, and nightly encrypted D1 database dumps.
- **Consequences:** Decouples durable archival storage from ephemeral compute and operational database limitations.

## ADR-003: App-Level Shared Persistent Request Pre-Reservation & Distributed Lease
- **Status:** Accepted
- **Context:** PSX data portal is a public utility. Aggressive scraping or multi-runner retries could trigger IP blocks or service degradation. Recording requests in memory loses count on runner crashes.
- **Decision:** Impose a hard app-level fuse of 250 requests per rolling 24 hours, stored in `state/budget_and_lease.json` in the private repository. Before opening any outbound network socket, the runner pre-reserves and commits the request quota remotely using optimistic concurrency (HTTP 409 retry loop with backoff). Distributed lease with 15-minute TTL coordinates runners. If quota is exhausted, collector fails closed.
- **Consequences:** Guarantees fair use, prevents runaway crash-loops from bypassing limits, and eliminates concurrent split-brain execution across runners.

## ADR-004: Dual-Gate Ingestion Security (Cloudflare Access + HMAC)
- **Status:** Accepted
- **Context:** Public exposure of staging endpoints or unauthenticated ingestion could lead to unauthorized database writes or data poisoning.
- **Decision:** All staging endpoints are gated by Cloudflare Access Free. The collector must present a Cloudflare Access Service Token (`CF-Access-Client-Id` / `CF-Access-Client-Secret`), and payload must be HMAC-signed with replay timestamp protection (+/- 300s window) and nonces.
- **Consequences:** Direct unauthenticated requests are blocked at Cloudflare's edge before consuming Worker CPU.

## ADR-005: AI as Compiler, Not Calculator
- **Status:** Accepted
- **Context:** LLMs produce non-deterministic calculations and hallucinations if asked to compute financial metrics directly.
- **Decision:** Gemini `gemini-2.5-flash` / `gemini-2.5-flash-lite` generates validated `ExperimentSpec` JSON conforming to a whitelisted DSL (BUY_HOLD, DCA, SMA_CROSS, RSI, etc.). The browser Web Worker computes equity curves, CAGR, and Sharpe ratios deterministically.
- **Consequences:** 100% reproducible backtests with zero LLM hallucination risk on financial outcomes.

## ADR-006: Cumulative Daily Manifests with SHA-256 Readback Verification
- **Status:** Accepted
- **Context:** Intraday polling runs execute multiple times per day. Overwriting a daily manifest on each run wipes out the catalog of earlier intraday files.
- **Decision:** `DurableArchiveManager` merges incoming verified file paths with existing entries in `manifests/YYYY-MM-DD.json` and records cycle executions in an immutable history array. All commits (gzip shards and manifests) undergo immediate readback verification via GET and SHA-256 hash comparison.
- **Consequences:** Preserves an unbroken audit trail of all intraday snapshots for every trading day.

## ADR-007: Atomic SQLite Replay Lock in D1
- **Status:** Accepted
- **Context:** Check-then-act validation of nonces in eventual consistency stores (like KV) allows replay race conditions under simultaneous requests.
- **Decision:** Anchor nonce replay protection in Cloudflare D1 using an atomic SQL insert `INSERT INTO seen_nonces (nonce, timestamp_sec)` leveraging SQLite's primary key constraint. KV is utilized purely as an optional edge read-cache.
- **Consequences:** Provable atomic replay rejection without race conditions.
