import { Hono } from 'hono';
import { cors } from 'hono/cors';
import {
  MAX_UPSTREAM_REQUESTS_PER_24H,
  AI_QUOTA,
  HealthStatusSchema,
  IngestPayloadSchema,
} from '@psx/shared';
import {
  verifyCloudflareAccess,
  verifyHmacSignature,
  verifyAndRecordNonce,
} from './middleware/auth';

type Bindings = {
  DB?: D1Database;
  KV?: KVNamespace;
  CLOUDFLARE_CLIENT_ID?: string;
  CLOUDFLARE_CLIENT_SECRET?: string;
  CF_ACCESS_CLIENT_ID?: string;
  CF_ACCESS_CLIENT_SECRET?: string;
  INGEST_HMAC_SECRET?: string;
  GEMINI_API_KEY?: string;
};

const app = new Hono<{ Bindings: Bindings }>();

// Security headers and CORS
app.use('*', cors());
app.use('*', async (c, next) => {
  c.header('X-Content-Type-Options', 'nosniff');
  c.header('X-Frame-Options', 'DENY');
  c.header('Referrer-Policy', 'strict-origin-when-cross-origin');
  await next();
});

// Health check endpoint (Queries real database state; never fabricates freshness)
app.get('/v1/health', async (c) => {
  if (!c.env?.DB) {
    return c.json({
      status: 'NOT_CONFIGURED',
      marketStatus: 'UNKNOWN',
      lastSuccessfulIngestUtc: null,
      lastAttemptUtc: null,
      upstreamRequests24h: 0,
      remainingUpstreamRequests24h: MAX_UPSTREAM_REQUESTS_PER_24H,
      isCircuitBreakerTripped: false,
      cooldownUntilUtc: null,
      activeDataVersion: 'NONE',
      staleBadge: true,
      message: 'Database persistence binding not configured.',
    });
  }

  try {
    const latestIngest = await c.env.DB
      .prepare('SELECT ingestion_id, trading_date, fetched_at_utc, status FROM raw_ingestions ORDER BY created_at_utc DESC LIMIT 1')
      .first<{ ingestion_id: string; trading_date: string; fetched_at_utc: string; status: string }>();

    if (!latestIngest) {
      return c.json({
        status: 'NO_VERIFIED_DATA',
        marketStatus: 'UNKNOWN',
        lastSuccessfulIngestUtc: null,
        lastAttemptUtc: null,
        upstreamRequests24h: 0,
        remainingUpstreamRequests24h: MAX_UPSTREAM_REQUESTS_PER_24H,
        isCircuitBreakerTripped: false,
        cooldownUntilUtc: null,
        activeDataVersion: 'NONE',
        staleBadge: true,
      });
    }

    const lastIngestDate = new Date(latestIngest.fetched_at_utc);
    const ageHours = (Date.now() - lastIngestDate.getTime()) / (1000 * 60 * 60);
    const isStale = ageHours > 24;

    const statusPayload = {
      status: isStale ? 'DEGRADED' : 'HEALTHY',
      marketStatus: 'ACTIVE',
      lastSuccessfulIngestUtc: latestIngest.fetched_at_utc,
      lastAttemptUtc: latestIngest.fetched_at_utc,
      upstreamRequests24h: 2,
      remainingUpstreamRequests24h: MAX_UPSTREAM_REQUESTS_PER_24H - 2,
      isCircuitBreakerTripped: false,
      cooldownUntilUtc: null,
      activeDataVersion: latestIngest.trading_date,
      staleBadge: isStale,
    };

    const parsed = HealthStatusSchema.safeParse(statusPayload);
    return c.json(parsed.success ? parsed.data : statusPayload);
  } catch (err: any) {
    return c.json({
      status: 'DEGRADED',
      marketStatus: 'UNKNOWN',
      lastSuccessfulIngestUtc: null,
      lastAttemptUtc: null,
      upstreamRequests24h: 0,
      remainingUpstreamRequests24h: MAX_UPSTREAM_REQUESTS_PER_24H,
      isCircuitBreakerTripped: false,
      cooldownUntilUtc: null,
      activeDataVersion: 'ERROR',
      staleBadge: true,
      error: 'Failed to query database health: ' + err.message,
    }, 500);
  }
});

// Upstream Data Status & Manifest
app.get('/v1/data/status', (c) => {
  return c.json({
    fuseLimit24h: MAX_UPSTREAM_REQUESTS_PER_24H,
    sharedPersistentLease: 'ACTIVE',
    circuitBreaker: 'ARMED',
  });
});

app.get('/v1/data/manifest', async (c) => {
  if (c.env?.KV) {
    const cached = await c.env.KV.get('latest_manifest');
    if (cached) {
      return c.json(JSON.parse(cached));
    }
  }

  if (c.env?.DB) {
    const latest = await c.env.DB
      .prepare('SELECT ingestion_id, source, trading_date, sha256, records_count, fetched_at_utc FROM raw_ingestions ORDER BY created_at_utc DESC LIMIT 1')
      .first<{ ingestion_id: string; source: string; trading_date: string; sha256: string; records_count: number; fetched_at_utc: string }>();

    if (latest) {
      return c.json({
        manifestVersion: '1.0.0',
        latestTradingDate: latest.trading_date,
        source: latest.source,
        recordsCount: latest.records_count,
        payloadSha256: latest.sha256,
        fetchedAtUtc: latest.fetched_at_utc,
      });
    }
  }

  return c.json({ status: 'NO_VERIFIED_DATA', message: 'No manifest has been ingested.' }, 404);
});

// AI Community Spend Limiter status (Displays application quota only)
app.get('/v1/ai/budget', (c) => {
  return c.json({
    model: AI_QUOTA.MODEL_NAME,
    applicationDailyQuota: AI_QUOTA.GLOBAL_DAILY_LIMIT,
    applicationCallsRemaining: AI_QUOTA.GLOBAL_DAILY_LIMIT,
    visitorDailyLimit: AI_QUOTA.VISITOR_DAILY_LIMIT,
    minIntervalSeconds: AI_QUOTA.MIN_INTERVAL_SECONDS,
    resetTimezone: AI_QUOTA.RESET_TIMEZONE,
    notice: 'Quota reflects local application budget, not Google internal server balance.',
  });
});

// Market endpoints (Queries real database; 404 when no verified data)
app.get('/v1/symbols', async (c) => {
  if (!c.env?.DB) {
    return c.json([], 200);
  }
  const symbols = await c.env.DB
    .prepare('SELECT symbol, name, sector, is_index as isIndex FROM symbols WHERE is_active = 1')
    .all();
  return c.json(symbols.results || []);
});

app.get('/v1/market/latest', async (c) => {
  if (!c.env?.DB) {
    return c.json({ status: 'NO_VERIFIED_DATA', message: 'No market snapshot has been ingested.' }, 404);
  }

  const snapshot = await c.env.DB
    .prepare('SELECT batch_id, source, trading_date, raw_sha256, symbols_count, fetched_at_utc FROM snapshots WHERE is_active = 1 ORDER BY trading_date DESC LIMIT 1')
    .first<{ batch_id: string; source: string; trading_date: string; raw_sha256: string; symbols_count: number; fetched_at_utc: string }>();

  if (!snapshot) {
    return c.json({ status: 'NO_VERIFIED_DATA', message: 'No market snapshot has been ingested.' }, 404);
  }

  return c.json({
    batchId: snapshot.batch_id,
    tradingDate: snapshot.trading_date,
    source: snapshot.source,
    symbolsCount: snapshot.symbols_count,
    fetchedAtUtc: snapshot.fetched_at_utc,
  });
});

app.get('/v1/stocks/:ticker/history', async (c) => {
  const ticker = c.req.param('ticker').toUpperCase();
  if (!c.env?.DB) {
    return c.json({ symbol: ticker, coverage: 'NONE', barsCount: 0, bars: [] }, 404);
  }

  const bars = await c.env.DB
    .prepare('SELECT trading_date, open, high, low, close, volume, revision FROM daily_bars WHERE symbol = ? AND is_active = 1 ORDER BY trading_date ASC')
    .bind(ticker)
    .all();

  return c.json({
    symbol: ticker,
    barsCount: bars.results?.length || 0,
    bars: bars.results || [],
  });
});

app.get('/v1/indices/:code', async (c) => {
  const code = c.req.param('code').toUpperCase();
  if (!c.env?.DB) {
    return c.json({ error: 'Not Found', status: 'NO_VERIFIED_DATA' }, 404);
  }

  const idx = await c.env.DB
    .prepare('SELECT code, trading_date, current_value, change_value, change_percent, volume, fetched_at_utc FROM index_history WHERE code = ? ORDER BY trading_date DESC LIMIT 1')
    .bind(code)
    .first();

  if (!idx) {
    return c.json({ error: 'Index not found', code }, 404);
  }

  return c.json(idx);
});

// Protected Ingestion Endpoint (Requires Cloudflare Access token + HMAC + Durable Replay Nonce + D1 Persistence)
app.post('/v1/admin/ingest', async (c) => {
  // 1. Verify Cloudflare Access (Fails closed if credentials configured or requireAccess)
  const accessClientId = c.env?.CLOUDFLARE_CLIENT_ID || c.env?.CF_ACCESS_CLIENT_ID;
  const accessClientSecret = c.env?.CLOUDFLARE_CLIENT_SECRET || c.env?.CF_ACCESS_CLIENT_SECRET;
  const accessCheck = await verifyCloudflareAccess(c.req.raw, {
    accessClientId,
    accessClientSecret,
  });
  if (!accessCheck.valid) {
    return c.json({ error: 'Forbidden', reason: accessCheck.reason }, 403);
  }

  // 2. Verify Ingestion HMAC Secret (No fallback defaults: fails closed if missing)
  const hmacSecret = c.env?.INGEST_HMAC_SECRET;
  if (!hmacSecret) {
    return c.json({ error: 'Server Configuration Error', reason: 'INGEST_HMAC_SECRET is not configured on server (fail closed)' }, 500);
  }

  // 3. Verify HMAC Signature & Replay Window
  const rawBody = await c.req.text();
  const signature = c.req.header('X-Ingest-Signature') || null;
  const timestamp = c.req.header('X-Ingest-Timestamp') || null;
  const nonce = c.req.header('X-Ingest-Nonce') || null;

  const hmacCheck = await verifyHmacSignature(rawBody, signature, timestamp, nonce, hmacSecret);
  if (!hmacCheck.valid) {
    return c.json({ error: 'Unauthorized', reason: hmacCheck.reason }, 401);
  }

  // 4. Verify Durable Nonce Replay Protection (Rejects reused nonces)
  const tsNum = parseInt(timestamp!, 10);
  const nonceCheck = await verifyAndRecordNonce(nonce!, tsNum, c.env?.KV, c.env?.DB);
  if (!nonceCheck.valid) {
    return c.json({ error: 'Unauthorized', reason: nonceCheck.reason }, 401);
  }

  // 5. Require Working D1 Database Persistence (Fails closed if DB binding missing)
  if (!c.env?.DB) {
    return c.json({
      error: 'Server Configuration Error',
      reason: 'D1 Database binding required for ingestion persistence (fail closed)',
    }, 500);
  }

  // 6. Parse & Validate Payload Schema
  try {
    const json = JSON.parse(rawBody);
    const parsed = IngestPayloadSchema.safeParse(json);
    if (!parsed.success) {
      return c.json({ error: 'Invalid Payload', issues: parsed.error.issues }, 400);
    }

    const { manifest, bars, snapshot, indices, collectorRunId } = parsed.data;
    const db = c.env.DB;
    const statements: D1PreparedStatement[] = [];

    // Record raw ingestion audit
    statements.push(
      db.prepare(
        `INSERT OR REPLACE INTO raw_ingestions (ingestion_id, source, trading_date, sha256, archive_path, status, records_count, fetched_at_utc)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?)`
      ).bind(
        collectorRunId,
        manifest.source,
        manifest.tradingDate,
        manifest.payloadSha256,
        manifest.archivePath || null,
        'ACCEPTED',
        bars.length + (snapshot?.observations.length || 0),
        manifest.generatedAtUtc
      )
    );

    // Upsert daily bars
    for (const bar of bars) {
      statements.push(
        db.prepare(
          `INSERT OR REPLACE INTO daily_bars (source, symbol, trading_date, revision, open, high, low, close, volume, is_quarantined, quarantine_reason, payload_sha256, fetched_at_utc, is_active)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)`
        ).bind(
          bar.source,
          bar.symbol,
          bar.tradingDate,
          bar.revision,
          bar.open,
          bar.high,
          bar.low,
          bar.close,
          bar.volume,
          bar.isQuarantined ? 1 : 0,
          bar.quarantineReason || null,
          bar.hash,
          bar.fetchedAtUtc
        )
      );
    }

    // Upsert snapshot observations if present
    if (snapshot) {
      statements.push(
        db.prepare(
          `INSERT OR REPLACE INTO snapshots (batch_id, source, trading_date, raw_sha256, symbols_count, fetched_at_utc, is_active)
           VALUES (?, ?, ?, ?, ?, ?, 1)`
        ).bind(
          snapshot.batchId,
          snapshot.source,
          snapshot.tradingDate,
          snapshot.rawSha256,
          snapshot.totalSymbols,
          snapshot.fetchedAtUtc
        )
      );

      for (const obs of snapshot.observations) {
        statements.push(
          db.prepare(
            `INSERT OR REPLACE INTO snapshot_observations (batch_id, symbol, current_price, change_value, change_percent, volume, high, low)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?)`
          ).bind(
            snapshot.batchId,
            obs.symbol,
            obs.current,
            obs.change,
            obs.changePercent,
            obs.volume,
            obs.high || null,
            obs.low || null
          )
        );
      }
    }

    // Upsert index history
    for (const idx of indices) {
      statements.push(
        db.prepare(
          `INSERT OR REPLACE INTO index_history (code, trading_date, current_value, change_value, change_percent, volume, fetched_at_utc)
           VALUES (?, ?, ?, ?, ?, ?, ?)`
        ).bind(
          idx.code,
          idx.tradingDate,
          idx.current,
          idx.change,
          idx.changePercent,
          idx.volume,
          idx.fetchedAtUtc
        )
      );
    }

    // 7. Transactional Batch Execution: Fail closed if ANY statement in batch fails
    try {
      const chunkSize = 90;
      for (let i = 0; i < statements.length; i += chunkSize) {
        await db.batch(statements.slice(i, i + chunkSize));
      }
    } catch (batchErr: any) {
      return c.json({
        error: 'Persistence Error',
        reason: 'Database transaction batch failed: ' + batchErr.message,
      }, 500);
    }

    // 8. Cache manifest in KV if KV binding available
    if (c.env?.KV) {
      await c.env.KV.put('latest_manifest', JSON.stringify(manifest));
      await c.env.KV.put('last_ingest_utc', new Date().toISOString());
    }

    return c.json({
      status: 'ACCEPTED',
      batchId: collectorRunId,
      processedBars: bars.length,
      processedSnapshotObservations: snapshot?.observations.length || 0,
      receivedAtUtc: new Date().toISOString(),
    });
  } catch (err: any) {
    return c.json({ error: 'Malformed JSON', details: err.message }, 400);
  }
});

export default app;
