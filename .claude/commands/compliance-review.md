# Compliance Review Command

Run a comprehensive compliance audit covering GDPR, PCI DSS, encryption, and MFA standards.

## Instructions

Perform a compliance audit in this order:

1. **GDPR Compliance**
   - Check for consent collection with audit trail (timestamp, IP, version)
   - Verify right-to-erasure implementation (complete deletion or anonymization)
   - Verify right-to-portability (JSON/CSV export endpoint)
   - Check data minimization (only necessary fields collected)
   - Verify retention policies and automated enforcement
   - Check for DPIA documentation (if high-risk processing)
   - Reference: `skills/security-review/gdpr-compliance.md`

2. **PCI DSS Compliance**
   - Verify client-side tokenization (Stripe Elements, no card data on server)
   - Check webhook signature verification on all payment endpoints
   - Ensure no card numbers, CVVs, or full expiry in logs/database
   - Verify payment services are network-isolated
   - Check idempotency for payment operations
   - Reference: `skills/security-review/pci-dss-compliance.md`

3. **Encryption Audit**
   - Check for AES-256-GCM on sensitive database fields (SSN, PII)
   - Verify encryption key management (KMS, env var, not hardcoded)
   - Check IV/nonce uniqueness per encryption operation
   - Verify key rotation procedure and version tracking
   - Check mobile encryption (AndroidKeyStore, iOS Keychain + CryptoKit)
   - Reference: `skills/security-review/application-encryption.md`

4. **MFA Assessment**
   - Check TOTP implementation (encrypted secrets, rate-limited verification)
   - Verify WebAuthn/Passkey support (if applicable)
   - Check OTP security (hashed, expiring, rate-limited, one-time use)
   - Verify backup code generation (hashed, one-time use)
   - Check biometric integration on mobile (BiometricPrompt, LAContext)
   - Reference: `skills/security-review/end-user-mfa.md`

5. **Zero Trust Posture**
   - Verify continuous authentication (not just at login)
   - Check for mTLS between internal services
   - Verify no implicit trust based on network location
   - Check ABAC/fine-grained access policies
   - Reference: `skills/security-review/zero-trust-architecture.md`

## Output

Produce a compliance report:

```
COMPLIANCE REVIEW: [PASS/FAIL]

GDPR:           [OK/X issues]
PCI DSS:        [OK/X issues]
Encryption:     [OK/X issues]
MFA:            [OK/X issues]
Zero Trust:     [OK/X issues]

Critical Issues: [count]
High Issues:     [count]
Medium Issues:   [count]

Compliant for production: [YES/NO]
```

List all findings with severity, standard reference, and remediation steps.

## Arguments

$ARGUMENTS can be:
- `full` - Complete compliance audit (default)
- `gdpr` - GDPR compliance only
- `pci` - PCI DSS compliance only
- `encryption` - Encryption audit only
- `mfa` - MFA assessment only
