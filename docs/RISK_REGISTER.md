# PSX Research Lab — Risk Register

| Risk ID | Category | Description | Severity | Probability | Mitigation Strategy |
|---|---|---|---|---|---|
| **RSK-001** | Upstream Blocking | PSX data portal returns HTTP 429 / 403 or blocks runner IPs due to high request frequency. | High | Medium | Hard app-level 250 req/24h fuse; polite 1.0s min interval; single whole-market snapshot (1 req covers ~496 stocks); 300s cooldown on 429 with Retry-After compliance. |
| **RSK-002** | Schedule Skew / Missed Runs | GitHub Actions cron triggers are delayed or dropped during peak hours. | Medium | High | Target non-zero minutes (e.g. minute 17/47); Cloudflare Cron watchdog detects stale data age; terminal displays clear "STALE DATA" badge; no destructive catch-up retry storm. |
| **RSK-003** | Cloudflare Free CPU Limit | Worker exceeds 10ms CPU limit during heavy computations or ingestion. | High | Low | Ingestion operates in bounded batches; backtesting computations delegated completely to client Web Worker; no heavy data processing on Worker. |
| **RSK-004** | Data Loss on Ephemeral Runners | Runner terminates without persisting collected raw market data. | High | Low | Pipeline requires committing gzipped raw payload and SHA-256 manifest to private GitHub data repo before concluding ingestion. |
| **RSK-005** | Accidental Cloud Spend | Unintended billable services or pay-as-you-go upgrades enabled. | Critical | Low | Zero-dollar contract: GitHub Actions billing budget set to $0; Cloudflare kept on Workers Free; Gemini unbilled project only; no R2 or paid DB. |
| **RSK-006** | AI Hallucinations in Calculations | AI produces incorrect financial returns or backtest metrics. | High | Medium | AI strictly acts as a compiler from natural language to whitelisted JSON DSL (`ExperimentSpec`). All backtesting math executed deterministically by audited TypeScript code. |
| **RSK-007** | Intraday Turnover Loss | Market current-session intraday buffer is cleared at market close before collector runs. | Medium | Medium | Late-session collection reconciles with EOD prices; gap disclosure in UI; no fabricated intraday history. |
