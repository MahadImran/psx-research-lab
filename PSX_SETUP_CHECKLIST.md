# PSX Research Lab — Cloud-only Owner Setup Checklist
Updated 2026-11-01. **No Orange Pi, Mac or other always-on personal hardware is required.** Never paste credentials into chat.

## Required for start (M0/M1)
- [ ] Create **private** GitHub repository `psx-research-lab`, enable standard GitHub-hosted Linux Actions runners. The development agent works from its authorized coding environment; collector executes in GitHub, not your home.
- [ ] Create second private GitHub repository `psx-research-data` for immutable compressed daily source archives, versioned manifests and encrypted D1 exports. Keep archives small, sharded and access-restricted. Check GitHub repo usage.
- [ ] Open GitHub Settings -> Billing and licensing -> Budgets and alerts. Set an enforced $0 paid-use budget/stop usage where available. Turn on 90% and 100% free-usage alerts. Do not enable larger/macOS runners or paid products. GitHub Free private repos provide 2,000 standard Linux Action minutes/month; normal jobs will use `timeout-minutes: 5`.
- [ ] Add `PSX_RESEARCH_LAB_MASTER_SPEC.md` and `PSX_CODING_AGENT_PROMPT.md` to app repo root. Start M0/M1 only; require a real hosted-runner source probe with redacted logs before any broad backfill.

## Required for collection and cloud-only staging (M2/M3)
- [ ] Create Cloudflare Free account at https://dash.cloudflare.com/, set up Workers, D1, KV and Cloudflare Access Free. No paid R2, no card-linked Cloud Run, no paid cron or VPN.
- [ ] Use Cloudflare Access to restrict the **entire** private staging hostname (API and static assets), including admin and ingestion endpoints. Independently test unauthorized fetch fails.
- [ ] Configure minimal Cloudflare API token/ingestion signing secret in GitHub Actions repository secrets (not code or messages). Secure separate archive repo write credentials as narrowly as possible. Keep ingestion HMAC secret in Cloudflare Worker Secrets. Create a dedicated Cloudflare Access service token for GitHub Actions ingestion and keep its client ID/secret in GitHub Actions Secrets; Access blocks requests before HMAC reaches Worker. Never put secrets in logs.
- [ ] Configure GitHub Actions `schedule` + `workflow_dispatch`; default hourly non-0-minute polling in PSX market hours, five-minute job timeout, upstream request limit 250/rolling 24h persisted in D1, distributed lease, 429/503 cooldown and safe idempotent publication. No end user triggers scraping.
- [ ] Create https://healthchecks.io/ Hobbyist Free monitor for collection heartbeat and missing-run alerts. Add its secret ping URL to GitHub Actions Secrets. Use Pakistan-session-aware schedule or separate business-day check.
- [ ] Enable Cloudflare Cron watchdog for last-success age and failure alerts. Allow bounded catch-up dispatch with narrowly scoped token only after user approves the needed repo permission, token rotation and monitoring; Cloudflare lightweight PSX fallback only after successful live connectivity/10ms CPU proof.
- [ ] Require daily encrypted D1 export to private GitHub data repo, hash manifests, no permanent dependence on Actions artifacts, and cloud-only monthly restore drills.

## AI (M5; can wait)
- [ ] Go to https://aistudio.google.com/apikey and create a *dedicated unbilled* free API project; verify real model availability and free RPM/TPM/RPD on https://aistudio.google.com/ (dashboard tabs may change).
- [ ] Place key only in Cloudflare Worker Secret; never in GitHub client output, chat or public code. Keep provider-side billing disabled and do not enable a paid fallback.
- [ ] Set app-managed community AI global and user quotas at or below the observed free-tier provider limits. Begin with fewer than 50/day if needed.

## Before any public launch (separate process)
- [ ] Resolve data rights for redistribution; conduct auth/security/abuse reviews and required notices.
- [ ] Prove historical data quality, restore, missed collection behavior and budget hard stops; explicitly approve any public exposure.
