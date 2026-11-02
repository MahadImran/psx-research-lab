# PSX Research Lab — Threat Model

## 1. Assets
1. **Market Data Records:** Canonical price bars, market snapshots, tick sequences, and historical indices.
2. **Private Strategy Formulations:** User-created quantitative experiments and backtesting configurations.
3. **Ingestion & Cloud Secrets:** HMAC secret, Cloudflare Access Service Token, Healthchecks ping URL, Gemini API key.
4. **Cloud Compute Quotas:** Cloudflare Free allowances, GitHub Actions minutes, Gemini Free RPD/RPM.

---

## 2. Threat Actors & Vectors

### A. Unauthorized Public Web Access
- **Threat:** Unauthenticated external visitors discovering staging URLs and accessing proprietary research or triggering billable load.
- **Mitigation:** Cloudflare Access (Zero Trust Free) encloses the entire staging hostname (`*.workers.dev` and web assets). Unauthenticated requests are rejected at the edge.

### B. Ingestion Poisoning & Replay Attacks
- **Threat:** Malicious actors forging ingestion batches or replaying intercepted collector payloads to corrupt market database.
- **Mitigation:**
  - Dual authentication: Cloudflare Access Service Token + HMAC-SHA256 signature.
  - Replay protection: Ingestion timestamp must fall within +/- 300 seconds of current server time.
  - Nonce validation: Each payload carries a unique nonce.
  - Schema & Quarantine: Payloads strictly validated against Zod / Python schemas. Out-of-bounds prices or negative volumes are quarantined.

### C. Resource Exhaustion / Denial of Service
- **Threat:** Exhaustion of Gemini AI quota or Cloudflare D1 write limits.
- **Mitigation:**
  - In-app spend limiter: Global limit 50/day, visitor limit 5/day, 30s minimum interval.
  - Atomic D1 slot reservation prior to provider calls.
  - Upstream request fuse: 250 requests/24h stops runaway loops.

### D. Upstream IP Blocking
- **Threat:** PSX data portal blacklisting runner IPs due to aggressive polling.
- **Mitigation:** Single owner collector architecture, minimum 1.0s interval between requests, 300s cooldown on HTTP 429/503 with Retry-After compliance. No proxy rotation.
