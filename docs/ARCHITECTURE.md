# PSX Research Lab — System Architecture

**Document Version:** 1.0.0 (Milestone 0 & 1)  
**Cost Posture:** Exactly \$0.00 / month (No credit-card dependencies, free tiers only)  
**Topology:** 100% Cloud-Hosted (No always-on home Mac, Orange Pi, or VPS)

---

## 1. High-Level Architecture Topology

```mermaid
flowchart TD
    subgraph GitHub_Cloud["GitHub Infrastructure (Free Private Repos)"]
        GHA["GitHub Actions (Linux Runners, 2000 free min/mo)\n• Scheduled cron (market hours PKT)\n• Ephemeral Python collector\n• SHA-256 validation & quarantine\n• Atomic D1 lease check"]
        DataRepo[("psx-research-data (Private)\n• Immutable raw .json.gz responses\n• Daily SHA-256 manifests\n• Nightly encrypted D1 exports")]
    end

    subgraph PSX_Upstream["Upstream Sources (Polite single collector)"]
        PSXDPS["Primary: dps.psx.com.pk via psx-dps\n• Rate-limited (1 req/s)\n• 250 requests/24h safety fuse\n• Respects 429 Retry-After & 503"]
        PSXData["Secondary: psxdata (Fallback only)"]
    end

    subgraph Cloudflare_Free["Cloudflare Workers Free Tier"]
        CF_Access["Cloudflare Access Free (Zero Trust)\nRestricts 100% staging hostname"]
        Worker["Cloudflare Worker (<10ms CPU)\n• Ingest validation (HMAC + Access Token)\n• AI Gateway (Gemini 3.5 Flash Lite)\n• Static asset serving (<25MiB/file)"]
        CF_Cron["Cloudflare Cron Watchdog\n• Minute 45 health monitor\n• Stale data badge triggers"]
        D1[("Cloudflare D1 (<=500MB)\n• Canonical daily bars & revisions\n• Shared 24h request budget\n• Distributed collector leases\n• AI visitor quotas & rate limits")]
        KV[("Cloudflare KV (<=1GB)\n• Latest whole-board snapshot\n• Fast immutable partitions")]
    end

    subgraph Client_Browser["Browser Client (Local Execution)"]
        ReactUI["Financial Terminal UI\n• Real-time / Stale badge\n• Karachi Market Time display\n• Light/Dark high-density mode"]
        WebWorker["Browser Web Worker\n• 100% Deterministic Backtesting\n• No AI math execution\n• Reproducible equity curves"]
    end

    subgraph Monitoring["External Free Observability"]
        Healthchecks["Healthchecks.io (Hobbyist Free)\nMissed collection heartbeat"]
    end

    %% Flows
    GHA -->|"Polite fetch (<=250 req/24h)"| PSXDPS
    GHA -->|"Fallback (if normal failure)"| PSXData
    GHA -->|"Commit compressed raw archives"| DataRepo
    GHA -->|"Ingest (HMAC + Access Token)"| CF_Access
    CF_Access --> Worker
    Worker --> D1
    Worker --> KV
    GHA -->|"Ping heartbeat"| Healthchecks
    CF_Cron -->|"Inspect latest timestamp"| D1
    ReactUI --> Worker
    ReactUI --> WebWorker
```

---

## 2. Core Architectural Decisions

1. **Single Owner Collector:** Only the ephemeral GitHub Actions runner runs Python and hits PSX endpoints. User request handlers never trigger scraping.
2. **Ephemeral Runners & Data Durability:** GitHub Actions runners are destroyed upon completion. All raw data is gzipped and committed to the private `psx-research-data` repository with SHA-256 manifests before ingestion into Cloudflare D1.
3. **Persistent Request Fuse:** A hard 250-request/24-hour limit is tracked in D1 and checked before every upstream request across all runners.
4. **Deterministic Math:** Gemini AI strictly compiles natural language into a versioned JSON DSL (`ExperimentSpec`). The browser Web Worker executes all calculations deterministically.
