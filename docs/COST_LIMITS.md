# PSX Research Lab — Cost Limits & Zero-Dollar Posture

**Mandate:** Exactly \$0.00 / month recurring cloud & API spend.

---

## 1. Cloudflare Workers Free Tier Budget
- **Worker Requests:** 100,000 requests / day (Staging access restricted via Cloudflare Access).
- **Worker CPU Time:** 10 ms / invocation (Heavy calculations delegated to browser Web Worker).
- **Subrequests:** Max 50 external calls / invocation.
- **D1 Database:**
  - Storage: <= 500 MB per database (Free limit).
  - Rows Read: 5,000,000 / day.
  - Rows Written: 100,000 / day.
  - Retention: 7 days Time Travel (Nightly offsite backups to `psx-research-data`).
- **KV Storage:**
  - Storage: <= 1 GB.
  - Reads: 100,000 / day.
  - Writes: 1,000 / day.
- **Cron Triggers:** 1 active trigger (Watchdog at minute 45). Free tier allows up to 5.
- **Forbidden:** No Cloudflare R2, no Paid Workers, no billable upgrades.

---

## 2. GitHub Actions Free Tier Budget
- **Monthly Linux Runner Minutes:** 2,000 standard minutes / month.
- **Allocation:**
  - Normal hourly collection: 8 runs / day × 22 trading days = 176 runs / month.
  - Execution duration: ~1.5 minutes per run = ~264 minutes / month.
  - Well under the 75% threshold (1,500 minutes).
- **Protective Settings:**
  - Job timeout: `timeout-minutes: 5` on all workflows.
  - GitHub Spending Limit set to \$0.00.
  - Alerts at 90% and 100% of free tier minutes.

---

## 3. Google Gemini Free Tier Budget
- **Model:** `gemini-3.5-flash-lite`.
- **Project Type:** Dedicated unbilled free-tier Google AI Studio project.
- **Application Quotas:**
  - Global: 50 requests / day.
  - Visitor: 5 requests / day.
  - Min Interval: 30 seconds.
  - Daily reset: Midnight `America/Los_Angeles` (aligned with Google RPD reset).
- **Forbidden:** No automatic credit-card billing or paid fallback.
