# PSX Research Lab — Architectural Decision Records (ADRs)

## ADR-001: Zero-Dollar Cloud-Only Hosting Topology
- **Status:** Accepted
- **Context:** The system requires scheduled automated collection, data persistence, and API serving with exactly \$0 recurring spend. No Mac, Orange Pi, or local hardware should be required.
- **Decision:** Utilize GitHub Actions standard hosted Linux runners (2,000 free minutes/month) for scheduled Python collectors; Cloudflare Workers Free (100k requests/day, D1 <=500MB, KV <=1GB) for serving; Google AI Studio Gemini Free tier for conversational strategy translation.
- **Consequences:** Ephemeral runners mean state must be persisted remotely. GitHub cron can jitter or skip runs; pipeline must handle best-effort scheduling gracefully with visible staleness badges.

## ADR-002: Durable Raw Archive in Dedicated Private Repository
- **Status:** Accepted
- **Context:** Actions artifacts expire (typically 90 days) and D1 Time Travel Free provides only 7 days retention. Loss of accepted historical market data is prohibited.
- **Decision:** Maintain a dedicated private repository (`psx-research-data`) for immutable compressed raw JSON files (`.json.gz`), daily SHA-256 manifests, and nightly encrypted D1 database dumps.
- **Consequences:** Decouples durable archival storage from ephemeral compute and operational database limitations.

## ADR-003: App-Level Shared Persistent 250-Request/24h Fuse
- **Status:** Accepted
- **Context:** PSX data portal is a public utility. Aggressive scraping or multi-runner retries could trigger IP blocks or service degradation.
- **Decision:** Impose a hard app-level fuse of 250 requests per rolling 24 hours, stored in D1 and checked before every outbound request across all runners. If exhausted, collector fails closed.
- **Consequences:** Guarantees fair use. Scheduled jobs prioritize whole-market snapshots (1 request covers ~496 stocks) rather than per-stock loops.

## ADR-004: Dual-Gate Ingestion Security (Cloudflare Access + HMAC)
- **Status:** Accepted
- **Context:** Public exposure of staging endpoints or unauthenticated ingestion could lead to unauthorized database writes or data poisoning.
- **Decision:** All staging endpoints are gated by Cloudflare Access Free. The collector must present a Cloudflare Access Service Token (`CF-Access-Client-Id` / `CF-Access-Client-Secret`), and payload must be HMAC-signed with replay timestamp protection (+/- 300s window) and nonces.
- **Consequences:** Direct unauthenticated requests are blocked at Cloudflare's edge before consuming Worker CPU.

## ADR-005: AI as Compiler, Not Calculator
- **Status:** Accepted
- **Context:** LLMs produce non-deterministic calculations and hallucinations if asked to compute financial metrics directly.
- **Decision:** Gemini `gemini-3.5-flash-lite` generates validated `ExperimentSpec` JSON conforming to a whitelisted DSL (BUY_HOLD, DCA, SMA_CROSS, RSI, etc.). The browser Web Worker computes equity curves, CAGR, and Sharpe ratios deterministically.
- **Consequences:** 100% reproducible backtests with zero LLM hallucination risk on financial outcomes.
