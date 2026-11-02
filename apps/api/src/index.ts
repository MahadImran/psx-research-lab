import { Hono } from 'hono';
import { cors } from 'hono/cors';
import {
  MAX_UPSTREAM_REQUESTS_PER_24H,
  AI_QUOTA,
  HealthStatusSchema,
  IngestPayloadSchema,
} from '@psx/shared';
import { verifyCloudflareAccess, verifyHmacSignature } from './middleware/auth';

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

// Health check endpoint
app.get('/v1/health', async (c) => {
  const isHealthy = true;
  const status = {
    status: isHealthy ? 'HEALTHY' : 'DEGRADED',
    marketStatus: 'CLOSED',
    lastSuccessfulIngestUtc: new Date().toISOString(),
    lastAttemptUtc: new Date().toISOString(),
    upstreamRequests24h: 12,
    remainingUpstreamRequests24h: MAX_UPSTREAM_REQUESTS_PER_24H - 12,
    isCircuitBreakerTripped: false,
    cooldownUntilUtc: null,
    activeDataVersion: '1.0.0',
    staleBadge: false,
  };

  const parsed = HealthStatusSchema.safeParse(status);
  return c.json(parsed.success ? parsed.data : status);
});

// Upstream Data Status & Manifest
app.get('/v1/data/status', (c) => {
  return c.json({
    activeVersion: '1.0.0',
    fuseLimit24h: MAX_UPSTREAM_REQUESTS_PER_24H,
    sharedPersistentLease: 'ACTIVE',
    circuitBreaker: 'ARMED',
  });
});

app.get('/v1/data/manifest', (c) => {
  return c.json({
    manifestVersion: '1.0.0',
    latestTradingDate: '2026-10-30',
    source: 'psx-dps',
    totalSymbols: 496,
  });
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

// Market endpoints (stubbed with type contract for M0/M1)
app.get('/v1/symbols', (c) => {
  return c.json([
    { symbol: 'OGDC', name: 'Oil & Gas Development Co.', isIndex: false },
    { symbol: 'ENGRO', name: 'Engro Corporation Ltd.', isIndex: false },
    { symbol: 'KSE100', name: 'KSE 100 Index', isIndex: true },
  ]);
});

app.get('/v1/market/latest', (c) => {
  return c.json({
    tradingDate: '2026-10-30',
    snapshotTimestamp: new Date().toISOString(),
    dataConfidence: 'VERIFIED_MOCK',
    stocksCount: 3,
  });
});

app.get('/v1/stocks/:ticker/history', (c) => {
  const ticker = c.req.param('ticker').toUpperCase();
  return c.json({
    symbol: ticker,
    coverage: '2022-2026',
    barsCount: 0,
    caveat: 'Historical bars available via durable manifests.',
  });
});

app.get('/v1/indices/:code', (c) => {
  const code = c.req.param('code').toUpperCase();
  return c.json({
    code,
    current: 85200.5,
    change: 450.2,
    changePercent: 0.53,
    tradingDate: '2026-10-30',
  });
});

// Protected Ingestion Endpoint (Requires Cloudflare Access token + HMAC)
app.post('/v1/admin/ingest', async (c) => {
  const accessConfig = {
    accessClientId: c.env?.CLOUDFLARE_CLIENT_ID || c.env?.CF_ACCESS_CLIENT_ID,
    accessClientSecret: c.env?.CLOUDFLARE_CLIENT_SECRET || c.env?.CF_ACCESS_CLIENT_SECRET,
  };

  // 1. Verify Cloudflare Access
  const accessCheck = await verifyCloudflareAccess(c.req.raw, accessConfig);
  if (!accessCheck.valid) {
    return c.json({ error: 'Forbidden', reason: accessCheck.reason }, 403);
  }

  // 2. Verify HMAC Signature
  const rawBody = await c.req.text();
  const signature = c.req.header('X-Ingest-Signature') || null;
  const timestamp = c.req.header('X-Ingest-Timestamp') || null;
  const nonce = c.req.header('X-Ingest-Nonce') || null;
  const hmacSecret = c.env?.INGEST_HMAC_SECRET || 'dev-hmac-secret-only';

  const hmacCheck = await verifyHmacSignature(rawBody, signature, timestamp, nonce, hmacSecret);
  if (!hmacCheck.valid) {
    return c.json({ error: 'Unauthorized', reason: hmacCheck.reason }, 401);
  }

  // 3. Parse & validate payload
  try {
    const json = JSON.parse(rawBody);
    const parsed = IngestPayloadSchema.safeParse(json);
    if (!parsed.success) {
      return c.json({ error: 'Invalid Payload', issues: parsed.error.issues }, 400);
    }

    const { manifest, bars, snapshot, indices, collectorRunId } = parsed.data;

    // 4. Persist to D1 if DB binding available
    if (c.env?.DB) {
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

      // Upsert snapshot if present
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

      // Execute batch (Cloudflare D1 supports max 100 statements per batch)
      if (statements.length > 0) {
        const chunkSize = 90;
        for (let i = 0; i < statements.length; i += chunkSize) {
          await db.batch(statements.slice(i, i + chunkSize));
        }
      }
    }

    // 5. Cache manifest in KV if KV binding available
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
