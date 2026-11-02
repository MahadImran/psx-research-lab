/**
 * Security & Ingestion Authorization Middleware
 * Uses Web Crypto API compatible with Cloudflare Workers Free (no Node crypto dependency)
 */

export interface AuthConfig {
  accessClientId?: string;
  accessClientSecret?: string;
  ingestHmacSecret?: string;
}

export async function verifyCloudflareAccess(
  req: Request,
  config: AuthConfig
): Promise<{ valid: boolean; reason?: string }> {
  // If Access credentials configured, require them
  if (config.accessClientId && config.accessClientSecret) {
    const clientId = req.headers.get('CF-Access-Client-Id');
    const clientSecret = req.headers.get('CF-Access-Client-Secret');

    if (!clientId || !clientSecret) {
      return { valid: false, reason: 'Missing Cloudflare Access service token headers' };
    }
    if (clientId !== config.accessClientId || clientSecret !== config.accessClientSecret) {
      return { valid: false, reason: 'Invalid Cloudflare Access service token' };
    }
  }
  return { valid: true };
}

export async function verifyHmacSignature(
  rawBody: string,
  signatureHeader: string | null,
  timestampHeader: string | null,
  nonceHeader: string | null,
  secret: string
): Promise<{ valid: boolean; reason?: string }> {
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
