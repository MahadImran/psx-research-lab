# PSX Research Lab — Setup Guide

**Cloud-Only Architecture:** No personal Mac, Orange Pi, or local server required for production.

---

## 1. Owner Setup Steps

### A. GitHub Configuration
1. Repository `MahadImran/psx-research-lab`: Private application codebase.
2. Repository `MahadImran/psx-research-data`: Private immutable data archive.
3. Configure GitHub Billing: Set Spending Limit to \$0.00 at `Settings -> Billing and licensing -> Spending limits`.
4. Add Repository Secrets in `psx-research-lab`:
   - `CF_ACCESS_CLIENT_ID`: Cloudflare Access Service Token Client ID.
   - `CF_ACCESS_CLIENT_SECRET`: Cloudflare Access Service Token Client Secret.
   - `INGEST_HMAC_SECRET`: Shared HMAC signing secret for ingestion.
   - `HEALTHCHECKS_PING_URL`: Healthchecks.io heartbeat ping URL.
   - `DATA_REPO_TOKEN`: GitHub fine-grained PAT with write access to `psx-research-data`.

### B. Cloudflare Configuration
1. Cloudflare Workers Free: Deploy API worker (`psx-research-lab-api`).
2. Cloudflare D1: Create database `psx-research-d1` and execute `apps/api/src/db/schema.sql`.
3. Cloudflare KV: Create KV namespace for snapshots.
4. Cloudflare Access Free: Create an application protecting the entire staging domain (`*.workers.dev`).
5. Provision Access Service Token for GitHub Actions.
6. Set Worker Secrets: `INGEST_HMAC_SECRET`, `GEMINI_API_KEY`.

### C. Google AI Studio (M5)
1. Create a dedicated unbilled project at [Google AI Studio](https://aistudio.google.com/apikey).
2. Obtain API key for `gemini-3.5-flash-lite`.
3. Save in Cloudflare Worker Secrets as `GEMINI_API_KEY`.
4. Verify project remains unbilled.

---

## 2. Local Development Setup
```bash
# 1. Install Node.js dependencies
pnpm install

# 2. Run system doctor check
make doctor

# 3. Run all tests
make test

# 4. Run local bounded probe
make probe
```
