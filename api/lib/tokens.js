import { createHash, randomBytes, timingSafeEqual } from 'node:crypto';

export const randomToken = () => randomBytes(32).toString('base64url');

export const sha256 = (value) => createHash('sha256').update(value).digest('hex');

export function hashMatches(value, expectedHex) {
  if (!value || !expectedHex) return false;
  return timingSafeEqual(Buffer.from(sha256(value), 'hex'), Buffer.from(expectedHex, 'hex'));
}
