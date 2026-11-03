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
  const nonces = new Set<string>();
  const ingestions: any[] = [];
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
          return null as T;
        },
        all: async () => ({ results: [] }),
        run: async () => {
          if (query.includes('seen_nonces')) {
            const n = boundParams[0];
            if (nonces.has(n)) {
              throw new Error('UNIQUE constraint failed: seen_nonces.nonce');
            }
            nonces.add(n);
          }
          if (query.includes('raw_ingestions')) {
            ingestions.push({
              ingestion_id: boundParams[0],
              source: boundParams[1],
              trading_date: boundParams[2],
              fetched_at_utc: boundParams[7],
              status: 'ACCEPTED',
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
});
