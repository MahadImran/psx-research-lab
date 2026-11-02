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

describe('API Routes & Security', () => {
  it('GET /v1/health returns healthy payload', async () => {
    const res = await app.request('/v1/health');
    expect(res.status).toBe(200);
    const body = (await res.json()) as any;
    expect(body.status).toBe('HEALTHY');
    expect(body.remainingUpstreamRequests24h).toBeLessThanOrEqual(250);
  });

  it('GET /v1/ai/budget shows application spend limit without exposing Google internals', async () => {
    const res = await app.request('/v1/ai/budget');
    expect(res.status).toBe(200);
    const body = (await res.json()) as any;
    expect(body.applicationDailyQuota).toBe(50);
    expect(body.model).toBe('gemini-3.5-flash-lite');
    expect(body.notice).toContain('local application budget');
  });

  it('POST /v1/admin/ingest rejects requests missing HMAC headers', async () => {
    const res = await app.request('/v1/admin/ingest', {
      method: 'POST',
      body: JSON.stringify({ test: 123 }),
    });
    expect(res.status).toBe(401);
  });

  it('POST /v1/admin/ingest rejects requests with expired timestamp (replay protection)', async () => {
    const staleTimestamp = Math.floor(Date.now() / 1000) - 400; // 400 seconds ago (> 300s limit)
    const nonce = 'random-nonce-12345';
    const body = JSON.stringify({ test: 123 });
    const message = `${staleTimestamp}.${nonce}.${body}`;
    const sig = await computeHmac(message, 'dev-hmac-secret-only');

    const res = await app.request('/v1/admin/ingest', {
      method: 'POST',
      headers: {
        'X-Ingest-Signature': sig,
        'X-Ingest-Timestamp': staleTimestamp.toString(),
        'X-Ingest-Nonce': nonce,
      },
      body,
    });
    expect(res.status).toBe(401);
    const data = (await res.json()) as any;
    expect(data.reason).toContain('300-second window');
  });

  it('POST /v1/admin/ingest accepts valid HMAC and valid IngestPayload', async () => {
    const timestamp = Math.floor(Date.now() / 1000);
    const nonce = 'valid-nonce-abcde';
    const payload = {
      manifest: {
        manifestVersion: '1.0.0',
        generatedAtUtc: new Date().toISOString(),
        tradingDate: '2026-10-30',
        source: 'psx-dps',
        totalBars: 1,
        totalSnapshots: 0,
        totalIndices: 0,
        payloadSha256: 'b'.repeat(64),
      },
      bars: [
        {
          source: 'psx-dps',
          symbol: 'OGDC',
          tradingDate: '2026-10-30',
          open: 135.0,
          high: null,
          low: null,
          close: 136.0,
          volume: 1000,
          revision: 0,
          isQuarantined: false,
          hash: 'c'.repeat(64),
          fetchedAtUtc: new Date().toISOString(),
        },
      ],
      indices: [],
      collectorRunId: 'test-run-001',
      timestamp,
      nonce,
    };
    const body = JSON.stringify(payload);
    const message = `${timestamp}.${nonce}.${body}`;
    const sig = await computeHmac(message, 'dev-hmac-secret-only');

    const res = await app.request('/v1/admin/ingest', {
      method: 'POST',
      headers: {
        'X-Ingest-Signature': sig,
        'X-Ingest-Timestamp': timestamp.toString(),
        'X-Ingest-Nonce': nonce,
      },
      body,
    });
    expect(res.status).toBe(200);
    const data = (await res.json()) as any;
    expect(data.status).toBe('ACCEPTED');
    expect(data.processedBars).toBe(1);
  });
});
