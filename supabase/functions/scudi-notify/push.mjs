// Scudi · Web Push without a library (decision 95): the message encrypted for one device (RFC 8291, aes128gcm, RFC 8188)
// and the sender's signature (VAPID, RFC 8292: an ES256 JSON Web Token). Plain WebCrypto, so the same file runs in the
// Edge Function (Deno) and in the tests (Node). Nothing here talks to the network: send() builds the request, the
// caller fetches it.

const te = new TextEncoder();
const subtle = globalThis.crypto.subtle;

export function b64u(bytes) {
  const b = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  let s = '';
  for (let i = 0; i < b.length; i += 0x8000) s += String.fromCharCode.apply(null, b.subarray(i, i + 0x8000));
  return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}
export function unb64u(str) {
  const s = String(str || '').replace(/-/g, '+').replace(/_/g, '/');
  const bin = atob(s + '='.repeat((4 - (s.length % 4)) % 4));
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}
function concat(...parts) {
  const n = parts.reduce((a, p) => a + p.length, 0), out = new Uint8Array(n);
  let o = 0; for (const p of parts) { out.set(p, o); o += p.length; }
  return out;
}
async function hmac(key, data) {
  const k = await subtle.importKey('raw', key, { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  return new Uint8Array(await subtle.sign('HMAC', k, data));
}
/* HKDF in two steps, as RFC 8291 writes it (every output here is at most one hash long) */
async function hkdf(salt, ikm, info, len) {
  const prk = await hmac(salt, ikm);
  return (await hmac(prk, concat(info, new Uint8Array([1])))).subarray(0, len);
}

/* ---------- the sender's key pair (VAPID): made once by the function, kept in the database ---------- */
export async function newKeys() {
  const kp = await subtle.generateKey({ name: 'ECDSA', namedCurve: 'P-256' }, true, ['sign', 'verify']);
  const pub = new Uint8Array(await subtle.exportKey('raw', kp.publicKey));
  const jwk = await subtle.exportKey('jwk', kp.privateKey);
  return { public_key: b64u(pub), private_jwk: { kty: jwk.kty, crv: jwk.crv, x: jwk.x, y: jwk.y, d: jwk.d } };
}
/* the JSON Web Token a push service checks: aud = the push service's origin, valid 12 hours, sub = who to contact */
export async function vapidAuth(endpoint, keys, sub, now) {
  const aud = new URL(endpoint).origin;
  const head = b64u(te.encode(JSON.stringify({ typ: 'JWT', alg: 'ES256' })));
  const body = b64u(te.encode(JSON.stringify({ aud, exp: Math.floor((now || Date.now()) / 1000) + 12 * 3600, sub })));
  const key = await subtle.importKey('jwk', { ...keys.private_jwk, ext: true }, { name: 'ECDSA', namedCurve: 'P-256' }, false, ['sign']);
  const sig = new Uint8Array(await subtle.sign({ name: 'ECDSA', hash: 'SHA-256' }, key, te.encode(head + '.' + body)));   /* r ‖ s, as JWS wants */
  return `vapid t=${head}.${body}.${b64u(sig)}, k=${keys.public_key}`;
}

/* ---------- the message, encrypted for one device (RFC 8291) ----------
   sub: { endpoint, p256dh, auth } as the browser gave them; text: the payload. `fixed` (tests only) supplies the
   sender's one-time key pair and the salt, for RFC 8291's worked example. */
export async function encrypt(sub, text, fixed) {
  const uaPub = unb64u(sub.p256dh), authSecret = unb64u(sub.auth);
  if (uaPub.length !== 65 || uaPub[0] !== 4 || authSecret.length !== 16) throw new Error('bad subscription keys');
  let asPriv, asPub;
  if (fixed) {
    asPub = unb64u(fixed.publicKey);
    asPriv = await subtle.importKey('jwk', { kty: 'EC', crv: 'P-256', d: fixed.privateKey, x: b64u(asPub.subarray(1, 33)), y: b64u(asPub.subarray(33, 65)), ext: true },
      { name: 'ECDH', namedCurve: 'P-256' }, false, ['deriveBits']);
  } else {
    const kp = await subtle.generateKey({ name: 'ECDH', namedCurve: 'P-256' }, true, ['deriveBits']);
    asPriv = kp.privateKey; asPub = new Uint8Array(await subtle.exportKey('raw', kp.publicKey));
  }
  const uaKey = await subtle.importKey('raw', uaPub, { name: 'ECDH', namedCurve: 'P-256' }, false, []);
  const ecdh = new Uint8Array(await subtle.deriveBits({ name: 'ECDH', public: uaKey }, asPriv, 256));
  const ikm = await hkdf(authSecret, ecdh, concat(te.encode('WebPush: info\0'), uaPub, asPub), 32);
  const salt = fixed ? unb64u(fixed.salt) : globalThis.crypto.getRandomValues(new Uint8Array(16));
  const cek = await hkdf(salt, ikm, te.encode('Content-Encoding: aes128gcm\0'), 16);
  const nonce = await hkdf(salt, ikm, te.encode('Content-Encoding: nonce\0'), 12);
  const plain = concat(te.encode(text), new Uint8Array([2]));   /* one record: the delimiter 2, no padding */
  const k = await subtle.importKey('raw', cek, { name: 'AES-GCM' }, false, ['encrypt']);
  const ct = new Uint8Array(await subtle.encrypt({ name: 'AES-GCM', iv: nonce }, k, plain));
  const rs = 4096, head = new Uint8Array(21);
  head.set(salt, 0); new DataView(head.buffer).setUint32(16, rs); head[20] = 65;
  return concat(head, asPub, ct);
}

/* the request for one device: { url, init } ready for fetch. ttl: seconds the push service may hold it; urgency:
   'high' for something happening now (a goal), 'normal' otherwise; topic: a later message with the same topic replaces
   one still undelivered */
export async function request(sub, payload, keys, opts) {
  const o = opts || {};
  const body = await encrypt(sub, typeof payload === 'string' ? payload : JSON.stringify(payload));
  if (body.length > 4096) throw new Error('message too long');
  const headers = {
    Authorization: await vapidAuth(sub.endpoint, keys, o.sub || 'https://scudi26.github.io/schedine-website/', o.now),
    'Content-Encoding': 'aes128gcm', 'Content-Type': 'application/octet-stream', TTL: String(o.ttl == null ? 3600 : o.ttl), Urgency: o.urgency || 'normal',
  };
  if (o.topic) headers.Topic = String(o.topic).replace(/[^A-Za-z0-9_-]/g, '').slice(0, 32);
  return { url: sub.endpoint, init: { method: 'POST', headers, body } };
}
/* what a push service's answer means for the device: delivered, gone for good (unsubscribed: remove it), or failed */
export function outcome(status) {
  if (status >= 200 && status < 300) return 'ok';
  if (status === 404 || status === 410) return 'gone';
  return 'failed';
}
