-- PSX Research Lab — Canonical D1 Schema
-- SQLite dialect for Cloudflare D1 Free (Max 500MB, 100k writes/day, 5M reads/day)

-- 1. Metadata and Sources
CREATE TABLE IF NOT EXISTS sources (
    source_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    base_url TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ACTIVE', -- ACTIVE, COOLDOWN, BLOCKED, PAUSED
    created_at_utc TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 2. Symbol Directory & Aliases
CREATE TABLE IF NOT EXISTS symbols (
    symbol TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    sector TEXT,
    is_index INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1,
    first_seen_date TEXT,
    last_seen_date TEXT,
    updated_at_utc TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 3. Raw Ingestions Audit
CREATE TABLE IF NOT EXISTS raw_ingestions (
    ingestion_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    trading_date TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    archive_path TEXT,
    status TEXT NOT NULL DEFAULT 'ACCEPTED', -- ACCEPTED, QUARANTINED, SUPERSEDED
    records_count INTEGER NOT NULL DEFAULT 0,
    fetched_at_utc TEXT NOT NULL,
    created_at_utc TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 4. Daily Bars (Immutable revisions, canonical identity: source + symbol + trading_date + revision)
CREATE TABLE IF NOT EXISTS daily_bars (
    source TEXT NOT NULL,
    symbol TEXT NOT NULL,
    trading_date TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 0,
    open REAL NOT NULL,
    high REAL, -- Nullable because eod() lacks high/low in psx-dps
    low REAL,  -- Nullable
    close REAL NOT NULL,
    volume INTEGER NOT NULL,
    is_quarantined INTEGER NOT NULL DEFAULT 0,
    quarantine_reason TEXT,
    data_grade TEXT NOT NULL DEFAULT 'GRADE_B',
    payload_sha256 TEXT NOT NULL,
    fetched_at_utc TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1, -- Only latest accepted revision is active
    PRIMARY KEY (source, symbol, trading_date, revision),
    FOREIGN KEY (symbol) REFERENCES symbols (symbol)
);

CREATE INDEX IF NOT EXISTS idx_daily_bars_lookup 
ON daily_bars (symbol, trading_date, is_active);

-- 5. Market Snapshots (Board-wide quotes)
CREATE TABLE IF NOT EXISTS snapshots (
    batch_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    trading_date TEXT NOT NULL,
    raw_sha256 TEXT NOT NULL,
    symbols_count INTEGER NOT NULL,
    fetched_at_utc TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS snapshot_observations (
    batch_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    current_price REAL NOT NULL,
    change_value REAL NOT NULL,
    change_percent REAL NOT NULL,
    volume INTEGER NOT NULL,
    high REAL,
    low REAL,
    PRIMARY KEY (batch_id, symbol),
    FOREIGN KEY (batch_id) REFERENCES snapshots (batch_id)
);

-- 6. Intraday Ticks (Preserves exact tick sequence so identical price/volume ticks are never dropped)
CREATE TABLE IF NOT EXISTS intraday_ticks (
    symbol TEXT NOT NULL,
    trading_date TEXT NOT NULL,
    sequence_id INTEGER NOT NULL,
    market_time_karachi TEXT NOT NULL,
    timestamp_utc TEXT NOT NULL,
    price REAL NOT NULL,
    volume INTEGER NOT NULL,
    PRIMARY KEY (symbol, trading_date, sequence_id)
);

-- 7. Indices
CREATE TABLE IF NOT EXISTS index_history (
    code TEXT NOT NULL,
    trading_date TEXT NOT NULL,
    current_value REAL NOT NULL,
    change_value REAL NOT NULL,
    change_percent REAL NOT NULL,
    volume INTEGER NOT NULL,
    fetched_at_utc TEXT NOT NULL,
    PRIMARY KEY (code, trading_date)
);

-- 8. Upstream Circuit Breaker & 24h Rolling Budget
-- Shared persistently across all ephemeral GitHub runners and Cloudflare watchdog
CREATE TABLE IF NOT EXISTS upstream_budget (
    budget_date TEXT PRIMARY KEY, -- YYYY-MM-DD
    requests_used INTEGER NOT NULL DEFAULT 0,
    requests_limit INTEGER NOT NULL DEFAULT 250,
    circuit_breaker_tripped INTEGER NOT NULL DEFAULT 0,
    tripped_reason TEXT,
    updated_at_utc TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS source_cooldowns (
    source TEXT PRIMARY KEY,
    cooldown_until_utc TEXT,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    last_error_code INTEGER,
    last_error_msg TEXT,
    updated_at_utc TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 9. Collector Lease (Distributed lock for ephemeral runners)
CREATE TABLE IF NOT EXISTS collector_leases (
    lease_id TEXT PRIMARY KEY, -- e.g. 'PSX_COLLECTOR'
    owner_runner_id TEXT NOT NULL,
    acquired_at_utc TEXT NOT NULL,
    expires_at_utc TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1
);

-- 10. AI Spend Limiter & Community Quota
CREATE TABLE IF NOT EXISTS quota_days (
    quota_date TEXT PRIMARY KEY, -- America/Los_Angeles date
    global_calls_used INTEGER NOT NULL DEFAULT 0,
    global_limit INTEGER NOT NULL DEFAULT 50,
    model_name TEXT NOT NULL DEFAULT 'gemini-3.5-flash-lite',
    updated_at_utc TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS quota_visitors (
    visitor_token_hash TEXT NOT NULL,
    quota_date TEXT NOT NULL,
    calls_used INTEGER NOT NULL DEFAULT 0,
    last_called_at_utc TEXT NOT NULL,
    active_call_in_progress INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (visitor_token_hash, quota_date)
);

-- 11. Experiments & Strategy Lab
CREATE TABLE IF NOT EXISTS experiments (
    experiment_id TEXT PRIMARY KEY,
    parent_id TEXT,
    name TEXT NOT NULL,
    spec_json TEXT NOT NULL,
    spec_hash TEXT NOT NULL,
    created_at_utc TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (parent_id) REFERENCES experiments (experiment_id)
);

-- 12. Health Heartbeats & Watchdog
CREATE TABLE IF NOT EXISTS health_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    event_type TEXT NOT NULL, -- INGEST_SUCCESS, INGEST_FAIL, WATCHDOG_CHECK, STALE_ALERT
    details_json TEXT,
    recorded_at_utc TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 13. Durable Nonce Replay Protection (Rejects duplicate requests)
CREATE TABLE IF NOT EXISTS seen_nonces (
    nonce TEXT PRIMARY KEY,
    timestamp_sec INTEGER NOT NULL,
    created_at_utc TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_seen_nonces_timestamp ON seen_nonces (timestamp_sec);

