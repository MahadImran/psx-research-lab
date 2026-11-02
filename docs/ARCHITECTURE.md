# PSX Research Lab — System Architecture

**Document Version:** 2.0.0 (Foundation Lockdown Verified)  
**Cost Posture:** Exactly $0.00 / month (No credit-card dependencies, free tiers only)  
**Topology:** 100% Cloud-Hosted (No always-on personal hardware, MacBook, Orange Pi, or VPS)  
**Repository Model:** Dual-Repository Split:
- **Application Repository (PUBLIC):** `MahadImran/psx-research-lab` (Code, architecture, CI workflows, tests, engineering portfolio showcase)
- **Data Archive Repository (PRIVATE):** `MahadImran/psx-research-data` (Immutable compressed market data `.json.gz`, daily cumulative SHA-256 manifests, disaster recovery state)

---

## 1. High-Level Architecture Topology

```mermaid
flowchart TD
    subgraph GitHub_Cloud["GitHub Infrastructure (Free Cloud Tier)"]
        GHA["GitHub Actions (Linux Runners, 2000 free min/mo)\n• Scheduled cron (market hours PKT)\n• Ephemeral Python collector\n• MarketCalendar (Karachi time session gate)\n• PersistentCoordinator (250 req/24h fuse & lease)\n• QuarantineAuditor (Schema & price audit)\n• EODReconciler (Settlement vs intraday)"]
        DataRepo[("MahadImran/psx-research-data (Strictly PRIVATE)\n• Immutable raw .json.gz responses (raw/YYYY/MM/DD/)\n• Daily cumulative SHA-256 manifests (manifests/YYYY-MM-DD.json)\n• Persistent cross-run lease & pre-reserved budget state")]
    end

    subgraph PSX_Upstream["Upstream Sources (Polite single collector)"]
        PSXDPS["Primary: dps.psx.com.pk via psx-dps\n• Rate-limited (1 req/s)\n• Dynamic Session Token Provider\n• 250 requests/24h safety fuse\n• Respects 429 Retry-After & 503"]
        PSXData["Secondary: psxdata (Fallback only)"]
    end

    subgraph Cloudflare_Free["Cloudflare Workers Free Tier"]
        CF_Access["Cloudflare Access Free (Zero Trust)\nRestricts 100% staging hostname\nValidated via CLOUDFLARE_CLIENT_ID / SECRET"]
        Worker["Cloudflare Worker (<10ms CPU)\n• Ingest validation (HMAC-SHA256 + Access Token)\n• AI Gateway (Gemini 2.5 Flash Lite)\n• Static asset serving (<25MiB/file)"]
        CF_Cron["Cloudflare Cron Watchdog\n• Minute 45 health monitor\n• Stale data badge triggers"]
        D1[("Cloudflare D1 (5GB Free)\n• Canonical daily bars & revisions\n• Snapshots & observations\n• Indices & raw ingestion audits\n• Atomic seen_nonces replay lock")]
        KV[("Cloudflare KV (1GB Free)\n• Latest whole-board snapshot\n• Active manifest & read-cache")]
    end

    subgraph Client_Browser["Browser Client (Local Execution)"]
        ReactUI["Financial Terminal UI\n• Real-time / Stale badge\n• Karachi Market Time display\n• High-density light/dark mode"]
        WebWorker["Browser Web Worker\n• 100% Deterministic Backtesting\n• No AI math execution\n• Reproducible equity curves"]
    end

    subgraph Monitoring["External Free Observability"]
        Healthchecks["Healthchecks.io (Hobbyist Free)\nStart, Success, Fail, Skip lifecycle pings\nZero false-positive alerts"]
    end

    %% Flows
    GHA -->|"Polite fetch (<=250 req/24h)"| PSXDPS
    GHA -->|"Fallback (if normal failure)"| PSXData
    GHA -->|"Commit compressed raw archives (.json.gz)"| DataRepo
    GHA -->|"Ingest (HMAC + Access Token)"| CF_Access
    CF_Access --> Worker
    Worker --> D1
    Worker --> KV
    GHA -->|"Lifecycle pings (/start, /fail, summary)"| Healthchecks
    CF_Cron -->|"Inspect latest timestamp"| D1
    ReactUI --> Worker
    ReactUI --> WebWorker
```

---

## 2. Core Architectural Decisions

1. **Dual-Repository Separation:**
   - The application codebase is intentionally public (`MahadImran/psx-research-lab`).
   - The financial data archive is strictly private (`MahadImran/psx-research-data`).
   - Under no circumstances does the public CI workflow leak private data archive tokens or raw third-party datasets into public build logs or artifacts.
2. **Single-Owner Collector:** Only ephemeral GitHub Actions runners run Python and query PSX endpoints. Public API user requests never trigger scraping.
3. **Session Token Extraction (`PSXTokenProvider`):**
   - Dynamic cookie and token negotiation extracts valid session credentials from PSX web endpoints.
   - Low-level network socket requests invoke `PersistentCoordinator.record_request()` to account for all network calls against quota.
4. **Market Trading Hours Awareness (`MarketCalendar`):**
   - All market hours are evaluated in `Asia/Karachi` (PKT, UTC+5).
   - Mon–Thu: 09:15–15:30 PKT.
   - Friday: 09:15–12:00 PKT (Session 1), 14:30–16:30 PKT (Session 2).
   - Post-close EOD reconciliation window: 15:30–18:00 PKT (16:30–19:00 on Fridays).
   - Out-of-hours collector triggers ping Healthchecks with skip reasons and exit cleanly without consuming upstream requests.
5. **Persistent Cross-Runner Coordination (`PersistentCoordinator`):**
   - Ephemeral GitHub runners coordinate through state stored in the private data repository (`state/budget_and_lease.json`).
   - A single-collector lease with a 15-minute TTL prevents overlapping runners.
   - Pre-reservation commits quota remotely *before* outbound socket calls, guaranteeing quota preservation across runner crashes.
   - Optimistic concurrency retries with exponential backoff on HTTP 409 conflicts.
6. **Immutable Durability (`DurableArchiveManager`):**
   - All upstream responses are gzipped (level 9) and sharded by `raw/YYYY/MM/DD/{source}_{endpoint}_{timestamp}_{hash8}.json.gz`.
   - Daily cumulative SHA-256 integrity manifests are committed to `manifests/YYYY-MM-DD.json`, accumulating files across all runs for the date without erasing morning snapshots.
   - Every commit undergoes immediate readback verification against the remote repository.
7. **Settlement Reconciliation (`EODReconciler`):**
   - Post-market daily reconciliation fetches official `POST /historical` datewise prices (712 symbols).
   - Discrepancies between preliminary intraday quotes and final settlement prices are flagged as revisions (`revision = 1`) and audited.
8. **Deterministic Client-Side Backtesting:**
   - AI is treated strictly as a compiler from natural language to structured JSON DSL.
   - Financial mathematics, portfolio accounting, and backtesting execute deterministically in the client's browser Web Worker.
