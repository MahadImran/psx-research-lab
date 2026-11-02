# PSX Research Lab — Foundation Handoff & Milestone 3 Gateway Document

**Status:** LOCKED & AWAITING M3 AUTHORIZATION  
**Date:** 2026-11-02  
**Target Architecture:** $0.00/mo Free Tier (Cloudflare + GitHub Actions + Private GitHub Data Repository)  

---

## 1. Foundation Operational State

As of 2026-11-02, Milestones 0, 1, and 2 are 100% complete, fully verified, and locked.

### Current Operating Baseline
- **Application Repository:** `MahadImran/psx-research-lab` (PUBLIC)
- **Data Archive Repository:** `MahadImran/psx-research-data` (PRIVATE)
- **Test Suite Status:**
  - TypeScript: **16 / 16 passed** (Vitest in CI)
  - Python: **63 / 63 passed** (Pytest in CI, including 8 Adversarial Chaos tests)
- **GitHub Actions Verification:**
  - `CI` (Run `41385970867`): PASS
  - `verify_durable_archive.yml` (Run `41386016819`): PASS (Live PSX connection, durable private commit, readback verification)
  - `collector.yml` (Run `41386086661`): PASS (`MARKET_CLOSED` clean skip, zero false alerts)
- **Unattended Schedule:** Disabled (`workflow_dispatch` only). No automated cron triggers are active.

---

## 2. Disaster Recovery & Archive Restore Procedures

If Cloudflare D1 or the API layer requires a complete database rebuild, canonical data can be replayed from the private data repository.

### Restore Procedure from Private Archive
1. **Clone Private Archive Repository:**
   ```bash
   git clone https://github.com/MahadImran/psx-research-data.git /tmp/psx-data
   ```
2. **Inspect Cumulative Daily Manifests:**
   Manifests are stored under `manifests/YYYY-MM-DD.json`. Each manifest contains:
   ```json
   {
     "tradingDate": "2026-11-02",
     "verifiedArchiveFiles": [
       "raw/2026/11/02/dps_index_summary_gha-41386016819.json.gz"
     ],
     "cycles": [...]
   }
   ```
3. **Decompress and Verify Payload Checksums:**
   For each verified file, decompress using standard `gzip -d` and compute SHA-256 to ensure zero corruption.
4. **Replay Ingestion into Cloudflare D1:**
   Using the local offline ingestion script or direct D1 batch SQL execution:
   ```bash
   wrangler d1 execute psx-market-db --file=apps/api/src/db/schema.sql
   # Execute batch insert from verified JSON
   ```

---

## 3. Emergency Incident Runbooks

### 3.1 Distributed Lease Deadlock Recovery
- **Condition:** A runner dies catastrophically without releasing the lease, and subsequent runs report `LeaseConflictError`.
- **Automatic Recovery:** The lease carries a 15-minute TTL (`expires_at`). Once the timestamp passes, the next runner automatically claims the expired lease.
- **Manual Override:**
  If immediate manual unblocking is necessary:
  1. Access `state/budget_and_lease.json` in `MahadImran/psx-research-data`.
  2. Set `"lease": null`.
  3. Commit file via GitHub web interface.

### 3.2 Upstream PSX 429 / Rate Limit Emergency
- **Condition:** PSX returns HTTP 429 Too Many Requests.
- **Action:**
  1. The collector activates `CooldownTracker`, setting the cooldown until the `Retry-After` header timestamp.
  2. The pipeline skips collection cycles until cooldown expires.
  3. Under no circumstances should proxy rotation or IP spoofing be implemented.

---

## 4. Milestone 3 Gateway & Dependencies

> [!IMPORTANT]
> **MILESTONE 3 IS CURRENTLY NOT AUTHORIZED.**
> The collector and storage foundation are locked. Implementation of Milestone 3 must not begin until the repository owner explicitly issues the start command.

### Exact Prerequisites for Milestone 3 (When Authorized)
When authorization is granted, Milestone 3 will encompass:
1. **Cloudflare D1 Database Provisioning:**
   - Execute schema migration (`apps/api/src/db/schema.sql`) onto free-tier D1 database `psx-market-db`.
2. **Cloudflare Workers API Deployment:**
   - Deploy `apps/api` to Cloudflare Workers free tier via Wrangler.
   - Configure environment variables: `INGEST_HMAC_SECRET`, `CF_ACCESS_TEAM_NAME`, `CF_ACCESS_AUD`.
3. **Cloudflare Access Free Configuration:**
   - Configure Zero Trust application policy to restrict all edge API endpoints behind single-user email OTP authentication (strictly enforcing zero public data leakage).
4. **Collector Ingestion Client Activation:**
   - Set `INGEST_API_URL` repository secret in `MahadImran/psx-research-lab` to target the deployed worker hostname.
   - Transition pipeline status from `ARCHIVE_COMMITTED_INGEST_PENDING` to `SUCCESS`.
5. **Gradual Cron Activation:**
   - Re-enable cron trigger in `collector.yml` during Karachi trading hours with safety fuses.
