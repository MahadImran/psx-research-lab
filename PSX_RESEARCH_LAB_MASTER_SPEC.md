# PSX Research Lab — Master Technical Specification
Date: 2026-11-01  |  Revision: cloud-only hosted collector (no personal hardware)  |  Status: proposal; integrations require live tests

## 0. Non-negotiable contract
- Monthly cloud/API spend target: USD $0. Keep Cloudflare on Workers Free and Gemini on an unbilled free-tier project. Never configure an automatic paid fallback, R2, paid AI endpoint, paid database, billable CI runner or paid observability service.
- Begin as a local/private research tool. Do not expose third-party PSX market-data archives to an unrestricted public audience before permission is resolved.
- No loss of an accepted historical observation without a recorded, recoverable version; no silent corruption. Maintain source provenance and tested backups. No free hosting stack promises zero loss or permanent uptime; document recovery point/limitations. No owner-operated hardware is required for collection, processing or backups.
- One PSX collector only. Read from our cache/database, not from PSX in user request handlers. Respect source rate limits, cooldown and upstream errors. Do not evade blocks.
- AI never computes simulated financial outcomes, executes generated code/SQL, calls arbitrary URLs or modifies market source records. It generates validated experiment definitions; the deterministic engine computes outcomes.
- Public data and user research/portfolio data must be separated. Credentials are never in repo, client bundle, logs or chat prompts.
- Build incrementally with acceptance tests, rollback and a commit after every milestone. Do not claim an external integration works without observing a successful real response.

## 1. Sources, confidence and access strategy
Primary PSX adapter: https://github.com/umairsandhu/psx-dps (pin a tested commit, inspect license/dependencies). Methods documented: `symbols`, `snapshot`, `market_watch`, `eod(symbol)`, `history_by_date(date)`, `history_by_month`, `intraday(symbol)`, `indices`, `index_constituents`. Snapshot ≈496 actively trading rows in one request; symbols directory ≈1,029, so absent market-watch symbol does not mean delisted. `eod()` covers about 5 years and lacks high/low. Current-session `intraday()` is per-symbol, not a market-wide historical intraday archive. It is not safe to schedule intraday downloads for every stock.
Secondary adapter: https://github.com/psxdata/psxdata, alpha Python API, alternative daily OHLCV source and independent parser. Do not use another adapter to bypass a PSX-issued block; fallback only for normal source failures and within the shared access budget.
Bootstrap archive: https://github.com/MuHamzaSheikh/PSXpert — advertises 475,244 stock daily records (100 stocks), 6,127 KSE100 records and years 2002–2026. This is third-party/unverified. Inspect dataset files, row counts, date range, licensing/metadata, duplicate dates, null fields, symbol history and adjustments. Retain quarantine flag until audited.
Official reference: https://dps.psx.com.pk/historical and https://www.psx.com.pk/psx/exchange/general/trading-hours. Treat undocumented endpoints as changeable.
Optional phase 4 macro: SBP EasyData, Pakistan Bureau of Statistics CPI, World Bank. Verify endpoint coverage, time alignment and provenance separately.

## 2. Target topology — 100% cloud-hosted, free-first
```
GitHub Actions (private repo, GitHub-hosted Ubuntu runner, no always-on process)
  schedule + workflow_dispatch (Asia/Karachi market-hours rules)
       -> Python psx-dps / psxdata (pinned, bounded, offline tests)
       -> obtain source response -> SHA-256 -> validate / quarantine / dedupe
       -> durable immutable compressed source archive in PRIVATE GitHub data repo/branch
       -> authenticated versioned upload and manifests -> Cloudflare Free
       -> job result + heartbeat to independent Healthchecks.io Hobbyist
Cloudflare Workers Free
  -> website / API / server-side free Gemini gateway
  -> D1: canonical daily market bars/indexes, experiments, auth, AI quotas,
         ingestion leases, upstream circuit breakers, health/manifest metadata
  -> KV: recent full-board snapshots / small immutable compressed partitions
  -> static versioned files (<25 MiB/file) for established historical series
  -> Cloudflare Cron independent WATCHDOG, optionally bounded snapshot fallback
Browser React + Web Worker: charts and deterministic backtesting
```
The GitHub-hosted runner is **ephemeral**; everything of value must be persisted remotely before job termination. There is no local always-on Orange Pi, Mac or VPS requirement. Use private source and private archive repos initially. Never rely on Actions artifacts, caches, or workflow logs for permanent archive storage: retention is limited. Monitor repository size and refuse to exceed repository limits; shard/compress by day/symbol/year rather than committing huge mutable files. If protected historical archives outgrow GitHub's acceptable repository usage, halt optional ingestion and request a new explicitly free durable storage plan; never silently delete records.

Cloudflare Access (Zero Trust Free) protects ALL staging asset/API routes. The collector must present an Access service token on ingestion requests (CF-Access-Client-Id / CF-Access-Client-Secret), in addition to HMAC; test that direct unauthenticated Worker requests are rejected. Avoid heavy compute inside Workers Free (10ms CPU limit); runs belong in GitHub Actions or browser Web Worker. Cloudflare Cron can perform small status checks and, only after a real successful external-connectivity/CPU test, a single whole-market emergency snapshot. The fallback must obey exactly the same distributed source budget/cooldown as GitHub; do not allow simultaneous collectors.

## 3. Storage and schema
Canonical hosted storage and separate archive:
- **D1**: accepted normalized daily price/index bars, revisions, users, experiments, quotas, health, cross-run leases, upstream request budget/cooldown and publisher manifests. Use bounded SQL batches; database <=500MB on Free, <=5GB/account, sharded if tested necessary.
- **KV**: latest market-board snapshot and compact immutable time-partitions; 1GB account storage and 1,000 writes/day on Free. Eventually consistent; not for locks or atomic budgets. Each stored snapshot has verified source/fetch timestamps.
- **Private GitHub archive repository / designated data branch**: immutable compressed raw responses organized by source/session/date, schema version, sha256 manifest, corrections and nightly encrypted export of user records where appropriate. Use GitHub API/token with narrowly scoped Contents permission; do not confuse a short-lived GitHub Actions artifact with backup.
- **Optional temporary SQLite** within each GitHub runner for bulk validation/reconciliation; ephemeral only. The pipeline must recover from D1 and private immutable archives on a fresh runner.

Required entities: `sources`, `raw_ingestions` (archive_path, sha256, source timestamps and observed status), `symbols` and aliases, `daily_bars` (source, date, revision, nullable high/low), `daily_bar_revisions`, `snapshots` and per-symbol snapshot observations, `intraday_ticks` (sequence/occurrence preserving legitimate repeated identical ticks), `index_constituent_history`, `corporate_actions`, `job_runs`, `data_manifests`, `ingest_batches`, `upstream_budget`, `source_cooldowns`, `collector_leases`, `users`, `experiments`, `experiment_revisions`, `chat_messages`, `quota_days`, `quota_visitors`, `ai_attempts`, `admin_audit`.

Daily bar identity is `(source, symbol, trading_date, revision)`; current accepted bars have a single active version. Store raw responses before promoting validated data; retain previous immutable versions, disclose historical coverage gaps and adjustments. For every source response include UTC fetch time, source-observed timestamp if provided, Asia/Karachi trading date, hash, status, batch ID and dataset version.

## 4. Data-ingestion pipeline — cloud scheduler
1. Use GitHub Actions `schedule` and `workflow_dispatch` on the default branch, using UTC cron or verified `timezone: Asia/Karachi`. Run 60- or 120-minute market-hour intervals, one close-time run after Friday's second session, and one daily post-close reconciliation; holiday/Ramadan overrides are data-driven. Avoid minute 0 (GitHub warns of delayed/dropped runs). GitHub Actions schedules are **best effort** and can be delayed or skipped: never claim guaranteed collection.
2. Runner fetches shared durable `collector_leases`, `source_cooldowns`, `upstream_budget` from D1 via protected API. Acquire lease with atomic compare-and-set/conditional update; expired lease recovery, no double collection even with a Cloudflare fallback. GitHub Actions workflow concurrency group cancels/rules out overlapping jobs. All source adapters share the same persistent remote request fuse because runners are ephemeral.
3. Fetch `psx.snapshot()` ONCE as the market-wide baseline, plus allowed/selected additional history. Respect `psx-dps` local cache, 1 request/sec, Retry-After, 429/503 cooldown and separate persistent global 250-request/rolling-24h safety fuse; refuse all source calls if budget API unavailable.
4. Save source bytes to staged compressed file and compute SHA-256 before parsing; validate schema, observed times, market-session semantics, symbol coverage, finite prices, volumes, high/low, suspicious revisions and staleness. Do not treat unchanged but successful response as failure. Quarantine suspect data, preserve last validated serving version.
5. Archive raw response/manifest into PRIVATE GitHub history (or another independently verified free durable archive) with explicit confirmation, then publish normalized idempotent chunks to Cloudflare. Use HMAC-signed timestamps and nonces, replay rejection, strict size limits, batch IDs and manifest last. A commit/Cloudflare failure may be recovered by a fresh runner from the surviving provider; incomplete batches never become the active manifest.
6. For historical reconciliation use `history_by_date()` where tested; independently verify close/volume; do not invent highs/lows missing from `eod()`. Add targeted backfill jobs within an independent small budget. Never re-download all stocks on every scheduled run.
7. Intraday: up to 5 chosen stock/index symbols initially; capped per-day requests, fetch full current-session ticks while available and store using source sequence rather than a naive (time, price, size) uniqueness constraint. Late collection across session turnover can irreversibly miss intraday data; warn user, never fabricate.
8. Publish heartbeat with `last_attempt`, `last_success`, `last_data_change`, `last_publish`, `upstream source timestamp`, `version`, `gap count` and source request count. Persist health independently in D1 and send success/failure heartbeat to Healthchecks.io Free. No user request triggers PSX collection.
9. Cloudflare scheduled watchdog examines last verified publish; on missed collection it alerts and, if configured, dispatches one GitHub Actions catch-up via a narrowly scoped token or attempts its own single-source snapshot ONLY after a tested CPU/egress proof. Cap retries and dispatches; never create an infinite retry storm. If GitHub unreachable, serve old validated data with explicit stale badge.

## 5. Upstream budgets and retry policies
- Maximum 250 source requests per rolling 24 hours **shared persistently across ALL ephemeral GitHub runners, manual jobs and Cloudflare fallback**; separate rate budget for one-time bootstrap/backfill, all protected by atomic D1 reservations. Do not rely on per-process/local library request budget as the only enforcement.
- Normally 6–8 whole-market snapshots per trading day (~one PSX upstream request each), limited selected intraday per-symbol calls, EOD reconciliations. All actual counts must be measured. Avoid 10:00, 11:00 etc GitHub cron peak times; choose nonzero minutes.
- HTTP 429/503 = honor Retry-After and record a shared circuit-breaker cooldown. Do not rotate source hosts/proxies to evade restrictions. 401/403 or unexpected schema = pause source and alert. Network timeouts/5xx get already bounded adapter retries and may be skipped until next scheduled run.
- D1 storage/budget API unavailable => fail closed for additional upstream requests or AI billing calls; use already published data; no unlimited retries.
- A failed Cloudflare upload is NOT permission to call PSX again: the durable archive contains the source response, so next cloud job retries idempotent publication from archive. Use bounded exponential backoff and jitter.
- GitHub Actions jobs have `timeout-minutes: 5` for normal hourly collection; a separate constrained manual/bootstrap job may be longer only after explicit budget approval. With approx. 8 scheduled runs x 22 trading days x 5 minutes = **880 maximum allocated Linux minutes/month** for the primary workflow before setup overhead or other CI jobs. Track account-wide usage and stop optional jobs around 75% of the included 2,000 private-repo minutes. Verify GitHub's 'Stop usage when budget limit is reached' setting and absence of spend-enabled paid overages. Never assume that a public repository is private merely because the website is protected.

## 6. Hosting limits and zero-charge behavior
- **Cloudflare Workers Free:** 100k requests/day, 10 ms CPU/invocation, 50 external subrequests/invocation, max 5 cron triggers/account. D1 Free: 5m rows read/day, 100k rows written/day, <=500 MB/database and <=5GB/account, seven days Time Travel. KV Free: 100k reads/day, 1k writes/day, <=1 GB; versioned static file assets <=25 MiB each. Reconfirm at provisioning.
- **GitHub Free private repositories:** 2,000 standard hosted Linux Actions minutes/month plus free repository hosting; schedule runs may be delayed or dropped. No larger/macOS runners, no billable Codespaces, no automatic paid upgrade, no linked paid runner. Set GitHub Actions billing budget with stop usage where available and 90% allowance alerts. Restrict CI jobs/pulls that can exhaust minutes; use timeouts, concurrency and explicit manual backfill gating.
- **Healthchecks.io Hobbyist:** free missed-job heartbeat monitoring (advertises up to 20 checks); no guarantee of external monitoring availability. Set schedules in Pakistan time with sensible grace to avoid false alerts outside market sessions.
- **Gemini:** unbilled free API project, server-only key, daily application quota <= observed free-tier Google rate limits. No pay-as-you-go fallback.
- **No R2, credit-card-dependent Cloud Run, paid cron/Python hosts, or household device**. Pause optional work before limits; use last trusted data and expose health status. Static/versioned data partitions reduce D1 and KV usage. Free-service limits, retention and terms can change; create an export/migration path.

## 7. AI contract and community spend-limiter
Provider: Google AI Studio Gemini API, model ID `gemini-3.5-flash-lite`; require an unbilled/free-tier project, confirm model is accessible on the account. Credentials Worker Secret `GEMINI_API_KEY` only. Turn OFF model tools not needed (Search/Maps/code execution). Do not send raw portfolio details or keys, source datasets, or unbounded chat history to provider; free tier may be used for product improvement.
AI's job: translate conversational requests and follow-up diffs into STRICT `ExperimentSpec` JSON matching versioned schema. Include asset identity, date range, portfolio cashflows, entry/exit signals, execution rule, order size, commission, slippage, reinvestment, benchmark, currency/inflation transforms, and data version. Model cannot invent backtest metrics, edit canonical data, run code, arbitrary SQL, fetch URLs, or silently choose ambiguous assumptions. Use a safe clarification when essential; otherwise show assumptions before execution.
Server validation: Zod/JSON schema, whitelisted operators (BUY_HOLD, DCA, SMA_CROSS, RSI, DIP_BUY, REBALANCE, etc.), bounded date ranges, permitted symbols/indicators; stable spec hashing; reject anything that cannot be expressed. Browser Web Worker engine computes equity curves, trade logs, Sharpe with disclosed convention, CAGR, max drawdown, drawdown duration, volatility, fees, benchmark, coverage and caveats.
Chat follow-ups reference `experiment_revision_id` and produce patches; retain parents/children for branching. A slider change does not spend AI requests. Explanation AI optional; favor deterministic analysis templates and use one AI interpretation request per turn.
App-managed limiter: configurable starting values global 50 requests/day, per-user 5/day, per-user cooldown 30s, one active call per user, max prompt tokens 8,000, max output 1,500, max conversation summaries and max request timeout. Actual Google free-tier limits vary per project and model; ask user to inspect AI Studio. Set app budget <= verified free provider limits, including RPD, RPM, TPM. Quotas reset in America/Los_Angeles to align with Gemini RPD reset, handling DST. Reserve slots atomically in D1 BEFORE calling provider; same request-id is idempotent; cap concurrent reservations; no new calls if D1 unavailable. Count ambiguous/timeout attempts conservatively so failures cannot bypass budget. On provider 429, trip a cooldown and pause all AI calls until quota recovery. No paid fallback. Public meter shows *app budget* (e.g. 37/50) and last refresh, never claims Google official remaining quota. Log tokens returned in usage_metadata and aggregate without storing API keys or sensitive prompts.
Before public beta add authentication/abuse controls, strong per-account budgets, Cloudflare Turnstile if appropriate, and explicit disclosure of free-tier data processing. Anonymous IP-cookie limits alone are spoofable.

## 8. Security and private staging
- Cloudflare Access Free must protect the complete staging website, including API and static assets. GitHub-hosted upload jobs must use a narrowly scoped Cloudflare Access service token plus HMAC for ingestion through Access; browser and source workflow auth must remain separate. Separate server-side admin authorization; only the controlled ingestion identity can publish data.
- GitHub Actions secrets for Cloudflare scoped API token, ingest signing secret, private backup/archive repository token, and Healthchecks.io ping URL. Rotate/revoke on exposure; use minimal repo and API permissions. Never put keys in git, source fixtures, logs, browser JS, AI prompts, screenshots or chat. Do not run pull-request code with write-capable secrets; pin third-party Actions by immutable SHA when practical.
- Cloudflare Worker Secrets for Gemini key, trusted issuer verification and shared ingest HMAC secret. Protect archive repository and manifests; don't publish market archives accidentally through a public branch or Pages deployment.
- HMAC timestamped uploads, nonce/replay protection, idempotent ingestion, transaction/quota checks in D1. Parameterized SQL; CSP; HTML/Markdown escaping; CORS/CSRF and auth; bounded upload/AI prompts. Account for untrusted upstream response and malicious CSV/JSON.
- Zero owner-hosted hardware or open inbound personal ports; ephemeral GitHub runners and Cloudflare handle all operations.

## 9. Backup, disaster recovery and continuity — no local device
- **Independent durable copies:** canonical serving dataset and application state in Cloudflare D1/KV plus immutable compressed raw source records, versions and manifests in a private GitHub data repository. A successful GitHub-hosted collection job MUST publish to a durable store before exiting; runners are destroyed after the job. Do not rely on Actions artifacts, logs or cache as permanent storage (retention typically 90 days and configurable).
- Export D1 (price metadata, AI budget, chats, experiment revisions) regularly as encrypted, checksum-verified compressed files into the private GitHub archive. Avoid commits per record and giant monolithic history files: write daily/monthly sharded archives and monitor repo growth. Check that automated backup files really appear and match their checksums.
- GitHub private archives and Cloudflare are separate providers but not infinite-capacity stores. If archive size or quota approaches limit, stop optional ingestion and raise a clear alert; do not delete unique accepted history without an alternative verified free durable destination.
- Cloudflare D1 Time Travel Free keeps only 7 days; offsite versioned exports are mandatory. Run automated restore drill on GitHub-hosted Linux runner monthly: rebuild SQLite or D1 scratch DB from archives, compare checksum/row counts/manifests and test selected historical backtests. Enforce job-duration and runner-minute budgets.
- If GitHub schedules are skipped, previously published data remains readable. Cloudflare watchdog reports staleness and can initiate ONE bounded retry/dispatch, using a scoped expiring/token rotation plan. If the market's current-session intraday buffer expires, some missed tick history cannot be recovered; show gaps and reconcile EOD prices instead. Do not claim zero downtime or zero data loss.
- Target market data recovery: latest verified published snapshot with visible source timestamps; chat/experiment RPO equals last successful encrypted D1 export unless real-time writes are also mirrored. Set RPO/RTO explicitly after dry-run tests.

## 10. Website pages and API outline
Frontend pages: Explore market, Stock details, Compare, Strategy Lab, Research Chat (branchable), Research Library, Data Health, Admin. Include timestamp, delay and data-confidence on every chart; show last-good when stale, no infinite spinners. Manual backtesting works without Gemini.
Worker endpoints (indicative, version all with `/v1`):
- GET `/v1/health`, `/v1/data/manifest`, `/v1/data/status`, `/v1/market/latest`, `/v1/symbols`, `/v1/stocks/:ticker/history?from=&to=`, `/v1/indices/:code`
- POST `/v1/experiments`, GET `/v1/experiments/:id`, POST `/v1/experiments/:id/branch`, POST `/v1/chat/interpret`, GET `/v1/ai/budget`
- POST `/v1/admin/ingest` signed+idempotent, GET `/v1/admin/runs`, GET `/v1/admin/quarantine`, POST `/v1/admin/pause` (admin auth), admin budget config
Use ETag, cache-control where safe; include source/dataset versions in API responses. Serve archived history from versioned static shards when possible.

## 11. Backtesting requirements
- Long-only cash equities in v1; fractional-share policy explicit, settlement/tax/fees assumptions explicit.
- Signals calculated from data available *at signal time*, execution at next eligible bar; no future leaks. For illiquid names, check volume and missing price days; impose optional max participation and slippage models.
- Total-return indices vs stock price returns must be identified and matched; compare like-for-like. Dividend adjustment is only exact if ex-dividend/corporate-action data is complete; otherwise flag omissions.
- Surviving members of 2026 KSE100 must not be used as historic universe for 2002 unless labeled biased; delisted data and index membership history may be missing.
- Golden tests with manually computed tiny portfolios, weekends, Friday splits, stale prices, no trades, fees, dividends, cashflow, inflation conversion, FX dates, overlapping signals, look-ahead boundaries, data corrections.

## 12. Milestones and acceptance criteria
**M0 — private GitHub repositories, CI, free-cost policy and cloud architecture.** No owner-operated host. Tests and secrets scanning; verify Github Actions monthly minute budget and Cloudflare no-paid posture; commit.
**M1 — GitHub-hosted live PSX test.** Use private hosted Ubuntu runner, test one snapshot, symbol list, two EOD stocks, selected intraday and source statuses. Record genuine upstream response, request count, hashes and runtime; no unvalidated assumptions; commit.
**M2 — durable, idempotent cloud collector.** Scheduled workflows, persisted cross-run upstream budgets/leases/cooldowns in D1, canonical validation and raw private GitHub archive. Prove clean runner restarts and re-run dedupe; commit.
**M3 — authenticated Cloudflare private serving and independent monitoring.** D1/KV/static manifest publication, Cloudflare Access, Cloudflare watchdog, Healthchecks.io heartbeat, D1 exports and successful cloud-only restore test. Intentionally skip a run and verify alert and stale-data UI; commit.
**M4 — frontend and deterministic backtesting.** Charts/search/compare; Web Worker computation and independent golden fixtures, source quality and stale/approximate labeling; commit.
**M5 — Gemini conversational research.** Structured DSL, follow-up patches, branches, safe explanation, D1 atomic shared/per-user quotas and 429 cooldown, real free-tier confirmation; commit.
**M6 — failover and disaster recovery hardening.** Test Cloudflare light fallback after proof of PSX accessibility and 10ms CPU compatibility; verify bad schema, outage, GitHub disabled schedule, expired dispatcher token, quotas at ceiling, stale retention and restore tests. No public launch; commit.
Each milestone ends with test output, source/cost evidence, health/failure test results, docs, commit ID and remaining owner setup.

## 13. Required setup from owner — no personal device
1. GitHub Free account: private application repo `psx-research-lab` and separate private versioned archive repo `psx-research-data` (or secure data branch). Enable Actions; inspect billing budgets and prevent paid overages. Grant the agent permissions only after explicitly authorizing deployment. Set secrets via GitHub Settings -> Secrets and variables -> Actions, not chat.
2. Cloudflare Free account: Workers, D1, KV, Access Free. Use `workers.dev` and protect complete development hostname. Provision minimal scoped cloud API/ingest credentials as GitHub Actions secrets; no billable product/upgrade.
3. Healthchecks.io Hobbyist Free: create collection-heartbeat monitor with trading-calendar-aware expected periods and sensible grace; save ping URL as GitHub Actions secret. No personal always-on machine required.
4. Google AI Studio unbilled free project: confirm selected Gemini model actually exists and has free tier for that project. Share only redacted numeric RPM/TPM/RPD; put API key in Cloudflare Secrets. Never link paid billing.
5. Choose hourly or 2-hour market refresh and up to 5 optional intraday tickers. Defaults: hourly and 5 named stocks/indexes; retain small request ceilings.
6. GitHub backup repo retention/size controls, recovery test destination and optional authorized extra free cloud backup if GitHub or Cloudflare change their conditions. No workstation, Orange Pi, self-hosted runners or paid VPS.

## 14. Verified reference URLs (as of 2026-11-01)
- PSX trading hours: https://www.psx.com.pk/psx/exchange/general/trading-hours
- psx-dps: https://github.com/umairsandhu/psx-dps
- psx-dps fair use: https://github.com/umairsandhu/psx-dps/blob/main/docs/FAIR-USE.md
- psx-dps cooldown policy: https://github.com/umairsandhu/psx-dps/blob/main/docs/STAYING-UNBLOCKED.md
- psxdata: https://github.com/psxdata/psxdata
- PSXpert: https://github.com/MuHamzaSheikh/PSXpert
- Cloudflare Workers Free: https://developers.cloudflare.com/workers/platform/limits/
- Cloudflare KV: https://developers.cloudflare.com/kv/platform/limits/
- Cloudflare D1 pricing: https://developers.cloudflare.com/d1/platform/pricing/
- Cloudflare D1 limits/time travel: https://developers.cloudflare.com/d1/platform/limits/
- Cloudflare Access: https://developers.cloudflare.com/workers/configuration/cloudflare-access/
- Cloudflare D1 exports: https://developers.cloudflare.com/d1/best-practices/import-export-data/
- Gemini models: https://ai.google.dev/gemini-api/docs/models
- Gemini pricing: https://ai.google.dev/gemini-api/docs/pricing
- Gemini rate limits: https://ai.google.dev/gemini-api/docs/rate-limits
- Gemini structured outputs: https://ai.google.dev/gemini-api/docs/structured-output
- GitHub Actions pricing: https://docs.github.com/en/billing/concepts/product-billing/github-actions
- GitHub schedule delays: https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows
- GitHub budget controls: https://docs.github.com/en/billing/how-tos/set-up-budgets
- Cloudflare Cron: https://developers.cloudflare.com/workers/configuration/cron-triggers/
- Healthchecks.io free: https://healthchecks.io/pricing/
- GitHub Actions artifact retention: https://github.blog/changelog/2026-08-27-actions-retention-will-cover-checks-workflow-runs-and-statuses/
