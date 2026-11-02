/**
 * Security & Ingestion Authorization Middleware
 * Uses Web Crypto API compatible with Cloudflare Workers Free (no Node crypto dependency).
 * Fails closed: no default fallback secrets, durable nonce replay protection, and strict Access validation.
 */

export interface AuthConfig {
  accessClientId?: string;
  accessClientSecret?: string;
  ingestHmacSecret?: string;
  requireAccess?: boolean;
}

export async function verifyCloudflareAccess(
  req: Request,
  config: AuthConfig
): Promise<{ valid: boolean; reason?: string }> {
  // If Access credentials configured, require them strictly
  if (config.accessClientId && config.accessClientSecret) {
    const clientId = req.headers.get('CF-Access-Client-Id') || req.headers.get('X-Cloudflare-Client-Id');
    const clientSecret = req.headers.get('CF-Access-Client-Secret') || req.headers.get('X-Cloudflare-Client-Secret');

    if (!clientId || !clientSecret) {
      return { valid: false, reason: 'Missing Cloudflare Access service token headers' };
    }
    if (clientId !== config.accessClientId || clientSecret !== config.accessClientSecret) {
      return { valid: false, reason: 'Invalid Cloudflare Access service token' };
    }
    return { valid: true };
  }

  // Fail closed if Access protection is required but not configured
  if (config.requireAccess) {
    return { valid: false, reason: 'Cloudflare Access protection required but not configured on server (fail closed)' };
  }

  return { valid: true };
}

export async function verifyHmacSignature(
  rawBody: string,
  signatureHeader: string | null,
  timestampHeader: string | null,
  nonceHeader: string | null,
  secret?: string
): Promise<{ valid: boolean; reason?: string }> {
  if (!secret || secret.length < 16) {
    return { valid: false, reason: 'Ingestion HMAC secret is not configured on server (fail closed)' };
  }

  if (!signatureHeader || !timestampHeader || !nonceHeader) {
    return { valid: false, reason: 'Missing required HMAC signature headers' };
  }

  // 1. Replay window check: allow max 300 seconds skew
  const now = Math.floor(Date.now() / 1000);
  const ts = parseInt(timestampHeader, 10);
  if (isNaN(ts) || Math.abs(now - ts) > 300) {
    return { valid: false, reason: 'Timestamp outside acceptable 300-second window' };
  }

  // 2. Compute expected HMAC: SHA256(timestamp + "." + nonce + "." + rawBody)
  try {
    const encoder = new TextEncoder();
    const keyData = encoder.encode(secret);
    const cryptoKey = await crypto.subtle.importKey(
      'raw',
      keyData,
      { name: 'HMAC', hash: 'SHA-256' },
      false,
      ['verify', 'sign']
    );

    const message = `${timestampHeader}.${nonceHeader}.${rawBody}`;
    const messageData = encoder.encode(message);

    // Convert hex signature header to Uint8Array
    if (signatureHeader.length !== 64) {
      return { valid: false, reason: 'Malformed HMAC signature format' };
    }
    const sigBytes = new Uint8Array(32);
    for (let i = 0; i < 32; i++) {
      sigBytes[i] = parseInt(signatureHeader.slice(i * 2, i * 2 + 2), 16);
    }

    const isValid = await crypto.subtle.verify('HMAC', cryptoKey, sigBytes, messageData);
    if (!isValid) {
      return { valid: false, reason: 'HMAC signature verification failed' };
    }

    return { valid: true };
  } catch (err: any) {
    return { valid: false, reason: `Crypto error: ${err.message}` };
  }
}

export async function verifyAndRecordNonce(
  nonce: string,
  timestampSec: number,
  kv?: KVNamespace,
  db?: D1Database
): Promise<{ valid: boolean; reason?: string }> {
  if (!nonce || nonce.length < 8) {
    return { valid: false, reason: 'Invalid nonce format' };
  }

  // 1. If KV available, use fast atomic expiration check
  if (kv) {
    const key = `nonce:${nonce}`;
    const existing = await kv.get(key);
    if (existing) {
      return { valid: false, reason: 'Nonce already used (replay attack detected)' };
    }
    // Store nonce with 10-minute TTL (600 seconds)
    await kv.put(key, timestampSec.toString(), { expirationTtl: 600 });
    return { valid: true };
  }

  // 2. If D1 available, use durable seen_nonces table
  if (db) {
    try {
      const existing = await db
        .prepare('SELECT nonce FROM seen_nonces WHERE nonce = ?')
        .bind(nonce)
        .first();
      if (existing) {
        return { valid: false, reason: 'Nonce already used (replay attack detected)' };
      }
      await db
        .prepare('INSERT INTO seen_nonces (nonce, timestamp_sec) VALUES (?, ?)')
        .bind(nonce, timestampSec)
        .run();
      return { valid: true };
    } catch (err: any) {
      // Primary key conflict caught here
      if (String(err).includes('UNIQUE') || String(err).includes('PRIMARY KEY')) {
        return { valid: false, reason: 'Nonce already used (replay attack detected)' };
      }
      return { valid: false, reason: `Nonce persistence check failed: ${err.message}` };
    }
  }

  // If neither KV nor D1 is present, fail closed
  return { valid: false, reason: 'Persistence binding required for durable replay protection' };
}
