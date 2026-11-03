import { describe, it, expect } from 'vitest';
import app from '../index';

async function computeHmac(message: string, secret: string): Promise<string> {
  const encoder = new TextEncoder();
  const key = await crypto.subtle.importKey(
    'raw',
    encoder.encode(secret),
    { name: 'HMAC', hash: 'SHA-256' },
    false,
    ['sign']
  );
  const sig = await crypto.subtle.sign('HMAC', key, encoder.encode(message));
  return Array.from(new Uint8Array(sig))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('');
}

function createMockKV(): KVNamespace {
  const store = new Map<string, string>();
  return {
    get: async (key: string) => store.get(key) || null,
    put: async (key: string, val: string) => {
      store.set(key, val);
    },
    delete: async (key: string) => {
      store.delete(key);
    },
  } as unknown as KVNamespace;
}

function createMockDB(): D1Database {
  const nonces = new Map<string, number>();
  const ingestions: any[] = [];
  const bars: any[] = [];
  const snapshots: any[] = [];
  const observations: any[] = [];

  return {
    prepare: (query: string) => {
      let boundParams: any[] = [];
      const stmt: any = {
        bind: (...params: any[]) => {
          boundParams = params;
          return stmt;
        },
        first: async <T = any>() => {
          if (query.includes('seen_nonces')) {
            const n = boundParams[0];
            return (nonces.has(n) ? { nonce: n } : null) as T;
          }
          if (query.includes('raw_ingestions')) {
            return (ingestions.length > 0 ? ingestions[ingestions.length - 1] : null) as T;
          }
          if (query.includes('snapshots')) {
            const active = snapshots.filter((s) => s.is_active === 1);
            return (active.length > 0 ? active[active.length - 1] : null) as T;
          }
          return null as T;
        },
        all: async () => {
          if (query.includes('daily_bars')) {
            const symbol = boundParams[0];
            let activeBars = bars.filter((b) => b.symbol === symbol && b.is_active === 1);
            let paramIdx = 1;
            if (query.includes('trading_date >=')) {
              const fromVal = boundParams[paramIdx++];
              activeBars = activeBars.filter((b) => b.trading_date >= fromVal);
            }
            if (query.includes('trading_date <=')) {
              const toVal = boundParams[paramIdx++];
              activeBars = activeBars.filter((b) => b.trading_date <= toVal);
            }
            return { results: activeBars };
          }
          if (query.includes('snapshot_observations')) {
            const batchId = boundParams[0];
            const obs = observations.filter((o) => o.batch_id === batchId);
            return { results: obs };
          }
          if (query.includes('symbols')) {
            return { results: [] };
          }
          return { results: [] };
        },
        run: async () => {
          if (query.includes('INSERT INTO seen_nonces')) {
            const n = boundParams[0];
            const ts = boundParams[1];
            if (nonces.has(n)) {
              throw new Error('UNIQUE constraint failed: seen_nonces.nonce');
            }
            nonces.set(n, ts);
          } else if (query.includes('DELETE FROM seen_nonces')) {
            const cutoff = boundParams[0];
            for (const [k, v] of nonces.entries()) {
              if (v < cutoff) nonces.delete(k);
            }
          } else if (query.includes('raw_ingestions')) {
            if (query.includes("UPDATE raw_ingestions SET status = 'ACCEPTED'")) {
              const id = boundParams[0];
              const ing = ingestions.find((i) => i.ingestion_id === id);
              if (ing) ing.status = 'ACCEPTED';
            } else {
              ingestions.push({
                ingestion_id: boundParams[0],
                source: boundParams[1],
                trading_date: boundParams[2],
                sha256: boundParams[3],
                records_count: boundParams[5],
                fetched_at_utc: boundParams[6] || boundParams[7] || new Date().toISOString(),
                status: 'STAGED',
              });
            }
          } else if (query.includes('daily_bars')) {
            if (query.includes('UPDATE daily_bars SET is_active = 1')) {
              const payloadSha256 = boundParams[0];
              for (const b of bars) {
                if (b.payload_sha256 === payloadSha256) {
                  b.is_active = 1;
                }
              }
            } else if (query.includes('INSERT OR REPLACE INTO daily_bars')) {
              bars.push({
                source: boundParams[0],
                symbol: boundParams[1],
                trading_date: boundParams[2],
                revision: boundParams[3],
                open: boundParams[4],
                high: boundParams[5],
                low: boundParams[6],
                close: boundParams[7],
                volume: boundParams[8],
                payload_sha256: boundParams[12],
                fetched_at_utc: boundParams[13],
                is_active: 0,
              });
            }
          } else if (query.includes('snapshots')) {
            if (query.includes('UPDATE snapshots SET is_active = 1')) {
              const batchId = boundParams[0];
              for (const s of snapshots) {
                if (s.batch_id === batchId) {
                  s.is_active = 1;
                }
              }
            } else if (query.includes('INSERT OR REPLACE INTO snapshots')) {
              snapshots.push({
                batch_id: boundParams[0],
                source: boundParams[1],
                trading_date: boundParams[2],
                raw_sha256: boundParams[3],
                symbols_count: boundParams[4],
                fetched_at_utc: boundParams[5],
                is_active: 0,
              });
            }
          } else if (query.includes('snapshot_observations')) {
            observations.push({
              batch_id: boundParams[0],
              symbol: boundParams[1],
              current_price: boundParams[2],
              change_value: boundParams[3],
              change_percent: boundParams[4],
              volume: boundParams[5],
              high: boundParams[6],
              low: boundParams[7],
            });
          }
          return { success: true };
        },
      };
      return stmt;
    },
    batch: async (statements: any[]) => {
      for (const stmt of statements) {
        if (stmt.run) await stmt.run();
      }
      return [];
    },
  } as unknown as D1Database;
}

describe('API Routes & Security', () => {
  const TEST_SECRET = 'super-secret-hmac-key-for-test-32chars';

  it('GET /v1/health returns NOT_CONFIGURED when DB is not bound', async () => {
    const res = await app.request('/v1/health');
    expect(res.status).toBe(200);
    const body = (await res.json()) as any;
    expect(body.status).toBe('NOT_CONFIGURED');
    expect(body.lastSuccessfulIngestUtc).toBeNull();
  });

  it('GET /v1/health returns NO_VERIFIED_DATA when DB is empty', async () => {
    const mockDb = createMockDB();
    const res = await app.request('/v1/health', {}, { DB: mockDb });
    expect(res.status).toBe(200);
    const body = (await res.json()) as any;
    expect(body.status).toBe('NO_VERIFIED_DATA');
    expect(body.lastSuccessfulIngestUtc).toBeNull();
    expect(body.staleBadge).toBe(true);
  });

  it('GET /v1/ai/budget shows application spend limit without exposing Google internals', async () => {
    const res = await app.request('/v1/ai/budget');
    expect(res.status).toBe(200);
    const body = (await res.json()) as any;
    expect(body.applicationDailyQuota).toBe(50);
    expect(body.model).toBe('gemini-3.5-flash-lite');
    expect(body.notice).toContain('local application budget');
  });

  const VALID_ACCESS_CLIENT_ID = 'test-cf-client-id';
  const VALID_ACCESS_CLIENT_SECRET = 'test-cf-client-secret';

  const defaultAccessHeaders = {
    'CF-Access-Client-Id': VALID_ACCESS_CLIENT_ID,
    'CF-Access-Client-Secret': VALID_ACCESS_CLIENT_SECRET,
  };

  const baseMockEnv = {
    CLOUDFLARE_CLIENT_ID: VALID_ACCESS_CLIENT_ID,
    CLOUDFLARE_CLIENT_SECRET: VALID_ACCESS_CLIENT_SECRET,
    INGEST_HMAC_SECRET: TEST_SECRET,
  };

  it('POST /v1/admin/ingest fails closed (403) when Cloudflare Access credentials are not configured on server', async () => {
    // Missing CLOUDFLARE_CLIENT_ID & SECRET in env
    const res = await app.request('/v1/admin/ingest', {
      method: 'POST',
      headers: defaultAccessHeaders,
      body: JSON.stringify({ test: 123 }),
    }, {
      INGEST_HMAC_SECRET: TEST_SECRET,
    });
    expect(res.status).toBe(403);
    const data = (await res.json()) as any;
    expect(data.reason).toContain('fail closed');
  });

  it('POST /v1/admin/ingest fails closed (403) when Cloudflare Access request headers are missing', async () => {
    const res = await app.request('/v1/admin/ingest', {
      method: 'POST',
      body: JSON.stringify({ test: 123 }),
    }, baseMockEnv);
    expect(res.status).toBe(403);
    const data = (await res.json()) as any;
    expect(data.reason).toContain('Missing Cloudflare Access service token');
  });

  it('POST /v1/admin/ingest fails closed (403) when Cloudflare Access credentials are invalid', async () => {
    const res = await app.request('/v1/admin/ingest', {
      method: 'POST',
      headers: {
        'CF-Access-Client-Id': 'wrong-id',
        'CF-Access-Client-Secret': 'wrong-secret',
      },
      body: JSON.stringify({ test: 123 }),
    }, baseMockEnv);
    expect(res.status).toBe(403);
    const data = (await res.json()) as any;
    expect(data.reason).toContain('Invalid Cloudflare Access service token');
  });

  it('POST /v1/admin/ingest fails closed (500) when INGEST_HMAC_SECRET is missing on server', async () => {
    const res = await app.request('/v1/admin/ingest', {
      method: 'POST',
      headers: defaultAccessHeaders,
      body: JSON.stringify({ test: 123 }),
    }, {
      CLOUDFLARE_CLIENT_ID: VALID_ACCESS_CLIENT_ID,
      CLOUDFLARE_CLIENT_SECRET: VALID_ACCESS_CLIENT_SECRET,
    });
    expect(res.status).toBe(500);
    const data = (await res.json()) as any;
    expect(data.reason).toContain('INGEST_HMAC_SECRET is not configured');
  });

  it('POST /v1/admin/ingest rejects requests missing HMAC headers', async () => {
    const res = await app.request(
      '/v1/admin/ingest',
      {
        method: 'POST',
        headers: defaultAccessHeaders,
        body: JSON.stringify({ test: 123 }),
      },
      baseMockEnv
    );
    expect(res.status).toBe(401);
  });

  it('POST /v1/admin/ingest rejects requests with expired timestamp (replay window)', async () => {
    const staleTimestamp = Math.floor(Date.now() / 1000) - 400; // > 300s
    const nonce = 'random-nonce-12345';
    const body = JSON.stringify({ test: 123 });
    const message = `${staleTimestamp}.${nonce}.${body}`;
    const sig = await computeHmac(message, TEST_SECRET);

    const res = await app.request(
      '/v1/admin/ingest',
      {
        method: 'POST',
        headers: {
          ...defaultAccessHeaders,
          'X-Ingest-Signature': sig,
          'X-Ingest-Timestamp': staleTimestamp.toString(),
          'X-Ingest-Nonce': nonce,
        },
        body,
      },
      baseMockEnv
    );
    expect(res.status).toBe(401);
    const data = (await res.json()) as any;
    expect(data.reason).toContain('300-second window');
  });

  it('POST /v1/admin/ingest fails closed (401) if D1 database binding is missing for nonce persistence', async () => {
    const timestamp = Math.floor(Date.now() / 1000);
    const nonce = 'nonce-no-db-12345';
    const payload = {
      manifest: {
        manifestVersion: '1.0.0',
        generatedAtUtc: new Date().toISOString(),
        tradingDate: '2026-10-30',
        source: 'psx-dps',
        totalBars: 0,
        totalSnapshots: 0,
        totalIndices: 0,
        payloadSha256: 'a'.repeat(64),
      },
      bars: [],
      indices: [],
      collectorRunId: 'test-run-no-db',
      timestamp,
      nonce,
    };
    const body = JSON.stringify(payload);
    const message = `${timestamp}.${nonce}.${body}`;
    const sig = await computeHmac(message, TEST_SECRET);

    const res = await app.request(
      '/v1/admin/ingest',
      {
        method: 'POST',
        headers: {
          ...defaultAccessHeaders,
          'X-Ingest-Signature': sig,
          'X-Ingest-Timestamp': timestamp.toString(),
          'X-Ingest-Nonce': nonce,
        },
        body,
      },
      {
        ...baseMockEnv,
        KV: createMockKV(),
      }
    );
    expect(res.status).toBe(401);
    const data = (await res.json()) as any;
    expect(data.reason).toContain('D1 Database binding required');
  });

  it('POST /v1/admin/ingest detects and blocks nonce replay attacks atomically via D1', async () => {
    const mockDb = createMockDB();
    const mockKv = createMockKV();
    const timestamp = Math.floor(Date.now() / 1000);
    const duplicateNonce = 'replay-nonce-attack-999';
    const payload = {
      manifest: {
        manifestVersion: '1.0.0',
        generatedAtUtc: new Date().toISOString(),
        tradingDate: '2026-10-30',
        source: 'psx-dps',
        totalBars: 0,
        totalSnapshots: 0,
        totalIndices: 0,
        payloadSha256: 'b'.repeat(64),
      },
      bars: [],
      indices: [],
      collectorRunId: 'test-run-replay',
      timestamp,
      nonce: duplicateNonce,
    };
    const body = JSON.stringify(payload);
    const message = `${timestamp}.${duplicateNonce}.${body}`;
    const sig = await computeHmac(message, TEST_SECRET);

    const mockEnv = {
      ...baseMockEnv,
      DB: mockDb,
      KV: mockKv,
    };

    // First request: valid
    const res1 = await app.request(
      '/v1/admin/ingest',
      {
        method: 'POST',
        headers: {
          ...defaultAccessHeaders,
          'X-Ingest-Signature': sig,
          'X-Ingest-Timestamp': timestamp.toString(),
          'X-Ingest-Nonce': duplicateNonce,
        },
        body,
      },
      mockEnv
    );
    expect(res1.status).toBe(200);

    // Second request with SAME nonce: must be rejected as replay attack!
    const res2 = await app.request(
      '/v1/admin/ingest',
      {
        method: 'POST',
        headers: {
          ...defaultAccessHeaders,
          'X-Ingest-Signature': sig,
          'X-Ingest-Timestamp': timestamp.toString(),
          'X-Ingest-Nonce': duplicateNonce,
        },
        body,
      },
      mockEnv
    );
    expect(res2.status).toBe(401);
    const data = (await res2.json()) as any;
    expect(data.reason).toContain('replay attack detected');
  });

  it('POST /v1/admin/ingest stages records then atomically publishes them (two-phase commit)', async () => {
    const mockDb = createMockDB();
    const timestamp = Math.floor(Date.now() / 1000);
    const nonce = 'two-phase-nonce-123';
    const payload = {
      manifest: {
        manifestVersion: '1.0.0',
        generatedAtUtc: new Date().toISOString(),
        tradingDate: '2026-10-30',
        source: 'psx-dps',
        totalBars: 1,
        totalSnapshots: 0,
        totalIndices: 0,
        payloadSha256: 'c'.repeat(64),
      },
      bars: [
        {
          source: 'psx-dps',
          symbol: 'SYS',
          tradingDate: '2026-10-30',
          revision: 0,
          open: 450.0,
          high: 460.0,
          low: 445.0,
          close: 455.0,
          volume: 50000,
          isQuarantined: false,
          dataGrade: 'GRADE_A',
          hash: 'c'.repeat(64),
          fetchedAtUtc: new Date().toISOString(),
        },
      ],
      indices: [],
      collectorRunId: 'test-run-staging-publish',
      timestamp,
      nonce,
    };
    const body = JSON.stringify(payload);
    const message = `${timestamp}.${nonce}.${body}`;
    const sig = await computeHmac(message, TEST_SECRET);

    const mockEnv = {
      ...baseMockEnv,
      DB: mockDb,
      KV: createMockKV(),
    };

    const res = await app.request(
      '/v1/admin/ingest',
      {
        method: 'POST',
        headers: {
          ...defaultAccessHeaders,
          'X-Ingest-Signature': sig,
          'X-Ingest-Timestamp': timestamp.toString(),
          'X-Ingest-Nonce': nonce,
        },
        body,
      },
      mockEnv
    );
    expect(res.status).toBe(200);

    // Verify idempotent re-ingest
    const nonce2 = 'two-phase-nonce-456';
    const message2 = `${timestamp}.${nonce2}.${body}`;
    const sig2 = await computeHmac(message2, TEST_SECRET);
    const resIdempotent = await app.request(
      '/v1/admin/ingest',
      {
        method: 'POST',
        headers: {
          ...defaultAccessHeaders,
          'X-Ingest-Signature': sig2,
          'X-Ingest-Timestamp': timestamp.toString(),
          'X-Ingest-Nonce': nonce2,
        },
        body,
      },
      mockEnv
    );
    expect(resIdempotent.status).toBe(200);
    const idempotentData = (await resIdempotent.json()) as any;
    expect(idempotentData.message).toContain('idempotent');
  });

  it('GET /v1/stocks/:ticker/history activates bars via manifest.payloadSha256 and supports from/to filtering', async () => {
    const mockDb = createMockDB();
    const mockEnv = {
      ...baseMockEnv,
      DB: mockDb,
      KV: createMockKV(),
    };

    const timestamp = Math.floor(Date.now() / 1000);
    const nonce = 'history-test-nonce-1';
    const payloadSha256 = 'd'.repeat(64);

    // Ingest 2 bars for OGDC on different dates where bar.hash != payloadSha256
    const payload = {
      manifest: {
        manifestVersion: '1.0.0',
        generatedAtUtc: new Date().toISOString(),
        tradingDate: '2026-10-31',
        source: 'psx-dps',
        totalBars: 2,
        totalSnapshots: 0,
        totalIndices: 0,
        payloadSha256,
      },
      bars: [
        {
          source: 'psx-dps',
          symbol: 'OGDC',
          tradingDate: '2026-10-30',
          revision: 0,
          open: 150.0,
          high: 155.0,
          low: 149.0,
          close: 153.0,
          volume: 1000000,
          isQuarantined: false,
          dataGrade: 'GRADE_A',
          hash: 'e'.repeat(64), // deliberately different from payloadSha256
          fetchedAtUtc: new Date().toISOString(),
        },
        {
          source: 'psx-dps',
          symbol: 'OGDC',
          tradingDate: '2026-10-31',
          revision: 0,
          open: 153.0,
          high: 157.0,
          low: 152.0,
          close: 156.0,
          volume: 1200000,
          isQuarantined: false,
          dataGrade: 'GRADE_A',
          hash: 'f'.repeat(64), // deliberately different from payloadSha256
          fetchedAtUtc: new Date().toISOString(),
        },
      ],
      indices: [],
      collectorRunId: 'run-history-ogdc',
      timestamp,
      nonce,
    };

    const body = JSON.stringify(payload);
    const message = `${timestamp}.${nonce}.${body}`;
    const sig = await computeHmac(message, TEST_SECRET);

    const ingestRes = await app.request(
      '/v1/admin/ingest',
      {
        method: 'POST',
        headers: {
          ...defaultAccessHeaders,
          'X-Ingest-Signature': sig,
          'X-Ingest-Timestamp': timestamp.toString(),
          'X-Ingest-Nonce': nonce,
        },
        body,
      },
      mockEnv
    );
    expect(ingestRes.status).toBe(200);

    // 1. Query full history: all active bars returned
    const allRes = await app.request('/v1/stocks/OGDC/history', {}, mockEnv);
    expect(allRes.status).toBe(200);
    const allData = (await allRes.json()) as any;
    expect(allData.symbol).toBe('OGDC');
    expect(allData.barsCount).toBe(2);

    // 2. Query with from filter
    const fromRes = await app.request('/v1/stocks/OGDC/history?from=2026-10-31', {}, mockEnv);
    expect(fromRes.status).toBe(200);
    const fromData = (await fromRes.json()) as any;
    expect(fromData.barsCount).toBe(1);
    expect(fromData.bars[0].trading_date).toBe('2026-10-31');

    // 3. Query with to filter
    const toRes = await app.request('/v1/stocks/OGDC/history?to=2026-10-30', {}, mockEnv);
    expect(toRes.status).toBe(200);
    const toData = (await toRes.json()) as any;
    expect(toData.barsCount).toBe(1);
    expect(toData.bars[0].trading_date).toBe('2026-10-30');

    // 4. Query out-of-range date
    const emptyRes = await app.request('/v1/stocks/OGDC/history?from=2026-11-05', {}, mockEnv);
    expect(emptyRes.status).toBe(200);
    const emptyData = (await emptyRes.json()) as any;
    expect(emptyData.barsCount).toBe(0);
  });

  it('GET /v1/market/latest returns snapshot and observations with ?observations=true', async () => {
    const mockDb = createMockDB();
    const mockEnv = {
      ...baseMockEnv,
      DB: mockDb,
      KV: createMockKV(),
    };

    const timestamp = Math.floor(Date.now() / 1000);
    const nonce = 'snapshot-obs-nonce-1';
    const payloadSha256 = 'a'.repeat(64);

    const batchId = '123e4567-e89b-12d3-a456-426614174000';
    const payload = {
      manifest: {
        manifestVersion: '1.0.0',
        generatedAtUtc: new Date().toISOString(),
        tradingDate: '2026-10-31',
        source: 'psx-dps',
        totalBars: 0,
        totalSnapshots: 2,
        totalIndices: 0,
        payloadSha256,
      },
      bars: [],
      snapshot: {
        batchId,
        tradingDate: '2026-10-31',
        source: 'psx-dps',
        rawSha256: payloadSha256,
        totalSymbols: 2,
        fetchedAtUtc: new Date().toISOString(),
        observations: [
          {
            symbol: 'OGDC',
            current: 155.0,
            change: 2.5,
            changePercent: 1.64,
            volume: 850000,
            high: 156.0,
            low: 152.0,
          },
          {
            symbol: 'ENGRO',
            current: 320.0,
            change: -1.2,
            changePercent: -0.37,
            volume: 420000,
            high: 323.0,
            low: 318.0,
          },
        ],
      },
      indices: [],
      collectorRunId: 'run-snapshot-test',
      timestamp,
      nonce,
    };

    const body = JSON.stringify(payload);
    const message = `${timestamp}.${nonce}.${body}`;
    const sig = await computeHmac(message, TEST_SECRET);

    const ingestRes = await app.request(
      '/v1/admin/ingest',
      {
        method: 'POST',
        headers: {
          ...defaultAccessHeaders,
          'X-Ingest-Signature': sig,
          'X-Ingest-Timestamp': timestamp.toString(),
          'X-Ingest-Nonce': nonce,
        },
        body,
      },
      mockEnv
    );
    expect(ingestRes.status).toBe(200);

    // Query latest without observations
    const latestRes = await app.request('/v1/market/latest', {}, mockEnv);
    expect(latestRes.status).toBe(200);
    const latestData = (await latestRes.json()) as any;
    expect(latestData.batchId).toBe(batchId);
    expect(latestData.symbolsCount).toBe(2);
    expect(latestData.observations).toBeUndefined();

    // Query latest with ?observations=true
    const latestWithObsRes = await app.request('/v1/market/latest?observations=true', {}, mockEnv);
    expect(latestWithObsRes.status).toBe(200);
    const latestWithObsData = (await latestWithObsRes.json()) as any;
    expect(latestWithObsData.batchId).toBe(batchId);
    expect(latestWithObsData.observations).toBeDefined();
    expect(latestWithObsData.observations.length).toBe(2);
    expect(latestWithObsData.observations[0].symbol).toBe('OGDC');
  });
});
