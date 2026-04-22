---
paths:
  - "**/*.ts"
  - "**/*.tsx"
  - "**/*.js"
  - "**/*.jsx"
---
# TypeScript/JavaScript Security

> This file extends [common/security.md](../common/security.md) with TypeScript/JavaScript specific content.

## Secret Management

```typescript
// NEVER: Hardcoded secrets
const apiKey = "sk-proj-xxxxx"

// ALWAYS: Environment variables
const apiKey = process.env.OPENAI_API_KEY

if (!apiKey) {
  throw new Error('OPENAI_API_KEY not configured')
}
```

## SSRF Prevention

```typescript
// NEVER: Fetch arbitrary user URLs
const resp = await fetch(req.query.url); // SSRF!

// ALWAYS: Validate against allowlist + block private IPs
import { URL } from 'url';
const ALLOWED_HOSTS = new Set(['api.stripe.com', 'api.github.com']);

function safeFetch(urlString: string) {
  const url = new URL(urlString);
  if (!ALLOWED_HOSTS.has(url.hostname)) throw new Error('Host not allowed');
  if (url.protocol !== 'https:') throw new Error('HTTPS required');
  return fetch(url.toString());
}
```

## Field-Level Encryption

```typescript
import crypto from 'crypto';

// AES-256-GCM — encrypt sensitive DB fields
function encryptField(plaintext: string, key: Buffer): { ciphertext: string; iv: string; tag: string } {
  const iv = crypto.randomBytes(12);
  const cipher = crypto.createCipheriv('aes-256-gcm', key, iv);
  let ct = cipher.update(plaintext, 'utf8', 'base64');
  ct += cipher.final('base64');
  return { ciphertext: ct, iv: iv.toString('base64'), tag: cipher.getAuthTag().toString('base64') };
}
```

## TOTP MFA

```typescript
import { authenticator } from 'otplib';

// Enroll: generate secret, show QR, store encrypted secret
const secret = authenticator.generateSecret();

// Verify: compare user code against secret
const isValid = authenticator.verify({ token: userCode, secret });
```

## Agent Support

- Use **security-reviewer** skill for comprehensive security audits
