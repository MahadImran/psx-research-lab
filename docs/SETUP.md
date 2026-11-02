# PSX Research Lab — Setup Guide

**Cloud-Only Architecture:** No personal Mac, Orange Pi, or local server required for production.  
**Spend Posture:** Strictly \$0.00 / month recurring costs.

---

## 1. Owner Setup Steps

### A. GitHub Configuration
1. Repository `MahadImran/psx-research-lab`: **PUBLIC** application codebase and engineering showcase.
2. Repository `MahadImran/psx-research-data`: **PRIVATE** immutable data archive and disaster recovery store.
3. Configure GitHub Billing: Set Spending Limit to \$0.00 at `Settings -> Billing and licensing -> Spending limits`.
4. Configure Repository Secrets in `MahadImran/psx-research-lab`:
   - `CLOUDFLARE_CLIENT_ID`: Cloudflare Access Service Token Client ID.
   - `CLOUDFLARE_CLIENT_SECRET`: Cloudflare Access Service Token Client Secret.
   - `DATA_REPO_TOKEN`: GitHub fine-grained PAT with scoped `contents: write` to `MahadImran/psx-research-data`.
   - `INGEST_HMAC_SECRET`: Shared HMAC-SHA256 signing secret for ingestion API.
   - `HEALTHCHECKS_PING_URL`: Healthchecks.io heartbeat ping URL.

### B. Cloudflare Configuration
1. Cloudflare Workers Free: Deploy API worker (`apps/api`).
2. Cloudflare D1: Create database `psx-research-d1` and execute `apps/api/src/db/schema.sql`.
3. Cloudflare KV: Create KV namespace for snapshots.
4. Cloudflare Access Free: Create an application protecting the staging domain (`*.workers.dev`).
5. Provision Access Service Token for GitHub Actions, saving credentials into GitHub repository secrets.
6. Set Worker Secrets via `wrangler secret put`:
   - `CLOUDFLARE_CLIENT_ID`
   - `CLOUDFLARE_CLIENT_SECRET`
   - `INGEST_HMAC_SECRET`
   - `GEMINI_API_KEY` (Milestone 5)

### C. Google AI Studio (Milestone 5)
1. Create a dedicated unbilled project at [Google AI Studio](https://aistudio.google.com/apikey).
2. Obtain API key for `gemini-3.5-flash-lite`.
3. Save in Cloudflare Worker Secrets as `GEMINI_API_KEY`.
4. Confirm project has no billing account attached.

---

## 2. Local Development & Verification
```bash
# 1. Install Node.js dependencies
pnpm install

# 2. Run prerequisite and security doctor check
bash scripts/doctor.sh

# 3. Run all TypeScript tests
pnpm test

# 4. Run all Python collector tests with coverage
pytest services/collector

# 5. Run collector CLI inspection
python -m services.collector.src.collector.cli calendar
python -m services.collector.src.collector.cli budget
```
