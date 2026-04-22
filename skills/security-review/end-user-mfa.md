| name | description |
|------|-------------|
| end-user-mfa | Use this skill when implementing multi-factor authentication for end users including TOTP, SMS OTP, WebAuthn/Passkeys, mobile biometrics, or MFA recovery flows. Covers web, API, and mobile platforms. |

# End-User MFA Skill

This skill ensures robust multi-factor authentication (MFA) implementation across all platforms, supporting TOTP, WebAuthn/Passkeys, SMS OTP, and biometric authentication.

## When to Activate

- Implementing user MFA enrollment and verification
- Adding TOTP (Google Authenticator, Authy) support
- Integrating WebAuthn/Passkeys for passwordless auth
- Adding SMS/email OTP as a second factor
- Implementing biometric authentication (mobile)
- Building MFA recovery flows (backup codes)
- Enforcing MFA for sensitive operations

## MFA Checklist

### 1. TOTP (Time-Based One-Time Passwords)

#### TOTP Setup & Verification

```typescript
// PASS: CORRECT — TOTP enrollment and verification
import { authenticator } from 'otplib';
import qrcode from 'qrcode';

// Generate TOTP secret for user enrollment
async function enrollTOTP(userId: string): Promise<TOTPEnrollment> {
  const secret = authenticator.generateSecret();

  // Store encrypted secret (not plaintext)
  await db.users.update({
    where: { id: userId },
    data: {
      totpSecret: await encrypt(secret), // AES-256-GCM encrypted
      totpEnabled: false, // Enable only after verification
    },
  });

  const otpAuthUrl = authenticator.keyuri(
    userId,
    'MyApp',
    secret,
  );

  const qrCodeDataUrl = await qrcode.toDataURL(otpAuthUrl);

  return { secret, qrCodeDataUrl };
}

// Verify TOTP code
async function verifyTOTP(userId: string, code: string): Promise<boolean> {
  const user = await db.users.findUnique({ where: { id: userId } });
  const secret = await decrypt(user.totpSecret);

  const isValid = authenticator.verify({ token: code, secret });

  if (!isValid) {
    await logSecurityEvent({
      category: 'auth',
      action: 'totp_verification_failed',
      userId,
      result: 'failure',
    });
  }

  return isValid;
}

// FAIL: WRONG — No encryption, no rate limiting
const secret = user.totpSecret; // Plaintext in DB
const isValid = authenticator.check(code, secret); // No failure logging
```

```python
# PASS: CORRECT — Python TOTP with pyotp
import pyotp
import qrcode
from io import BytesIO
from app.encryption import encrypt_field, decrypt_field

def enroll_totp(user_id: str) -> dict:
    secret = pyotp.random_base32()

    # Store encrypted
    encrypted_secret = encrypt_field(secret)
    db.execute(
        update(User).where(User.id == user_id).values(
            totp_secret=encrypted_secret,
            totp_enabled=False,
        )
    )

    totp = pyotp.TOTP(secret)
    provisioning_uri = totp.provisioning_uri(
        name=user_id, issuer_name="MyApp"
    )

    return {"secret": secret, "provisioning_uri": provisioning_uri}

def verify_totp(user_id: str, code: str) -> bool:
    user = db.query(User).filter(User.id == user_id).first()
    secret = decrypt_field(user.totp_secret)
    totp = pyotp.TOTP(secret)
    return totp.verify(code, valid_window=1)  # Allow 30s clock skew
```

#### Verification Steps

- [ ] TOTP secret encrypted at rest (not plaintext in DB)
- [ ] QR code generated for authenticator app enrollment
- [ ] Verification required before enabling TOTP
- [ ] Clock skew tolerance configured (1-2 windows)
- [ ] Rate limiting on TOTP verification attempts
- [ ] Failed attempts logged as security events

### 2. WebAuthn / Passkeys

#### WebAuthn Registration

```typescript
// PASS: CORRECT — WebAuthn registration with SimpleWebAuthn
import {
  generateRegistrationOptions,
  verifyRegistrationResponse,
} from '@simplewebauthn/server';

const rpName = 'MyApp';
const rpID = 'myapp.com';
const origin = 'https://myapp.com';

async function startWebAuthnRegistration(userId: string) {
  const user = await db.users.findUnique({ where: { id: userId } });
  const existingDevices = await db.credentials.findMany({ where: { userId } });

  const options = await generateRegistrationOptions({
    rpName,
    rpID,
    userID: userId,
    userName: user.email,
    attestationType: 'none', // For most apps, 'none' is sufficient
    excludeCredentials: existingDevices.map((d) => ({
      id: d.credentialId,
      type: 'public-key',
    })),
    authenticatorSelection: {
      residentKey: 'preferred',        // Passkey support
      userVerification: 'preferred',   // Biometric/PIN
    },
  });

  // Store challenge for verification
  await db.challenges.create({
    data: { userId, challenge: options.challenge, expiresAt: addMinutes(new Date(), 5) },
  });

  return options;
}

async function finishWebAuthnRegistration(userId: string, response: RegistrationResponseJSON) {
  const challenge = await db.challenges.findFirst({
    where: { userId, expiresAt: { gt: new Date() } },
    orderBy: { createdAt: 'desc' },
  });

  const verification = await verifyRegistrationResponse({
    response,
    expectedChallenge: challenge.challenge,
    expectedOrigin: origin,
    expectedRPID: rpID,
  });

  if (verification.verified && verification.registrationInfo) {
    await db.credentials.create({
      data: {
        userId,
        credentialId: Buffer.from(verification.registrationInfo.credentialID),
        publicKey: Buffer.from(verification.registrationInfo.credentialPublicKey),
        counter: verification.registrationInfo.counter,
      },
    });
  }

  return verification.verified;
}
```

#### Verification Steps

- [ ] WebAuthn RP ID and origin properly configured
- [ ] Challenge stored server-side with expiry
- [ ] Credential public key stored securely
- [ ] Counter verified to detect cloned authenticators
- [ ] Multiple devices supported per user
- [ ] Fallback to TOTP or backup codes available

### 3. SMS/Email OTP

#### OTP Generation & Verification

```typescript
// PASS: CORRECT — Secure OTP with rate limiting and expiry
import crypto from 'crypto';

async function sendOTP(userId: string, channel: 'sms' | 'email'): Promise<void> {
  // Rate limit: max 3 OTPs per 10 minutes
  const recentOTPs = await db.otps.count({
    where: { userId, createdAt: { gt: subMinutes(new Date(), 10) } },
  });
  if (recentOTPs >= 3) throw new Error('Too many OTP requests');

  // Generate 6-digit cryptographically secure OTP
  const otp = crypto.randomInt(100000, 999999).toString();

  // Store hashed OTP (never plaintext)
  const hashedOTP = await bcrypt.hash(otp, 10);
  await db.otps.create({
    data: {
      userId,
      hash: hashedOTP,
      channel,
      expiresAt: addMinutes(new Date(), 5), // 5-minute expiry
      attempts: 0,
    },
  });

  if (channel === 'sms') {
    await twilioClient.messages.create({
      body: `Your verification code is: ${otp}`,
      to: user.phone,
      from: process.env.TWILIO_PHONE,
    });
  } else {
    await sendEmail(user.email, 'Verification Code', `Your code: ${otp}`);
  }
}

async function verifyOTP(userId: string, code: string): Promise<boolean> {
  const otp = await db.otps.findFirst({
    where: { userId, expiresAt: { gt: new Date() } },
    orderBy: { createdAt: 'desc' },
  });

  if (!otp) return false;

  // Max 5 attempts per OTP
  if (otp.attempts >= 5) {
    await db.otps.delete({ where: { id: otp.id } });
    return false;
  }

  await db.otps.update({ where: { id: otp.id }, data: { attempts: { increment: 1 } } });

  const isValid = await bcrypt.compare(code, otp.hash);
  if (isValid) {
    await db.otps.delete({ where: { id: otp.id } }); // One-time use
  }

  return isValid;
}

// FAIL: WRONG — Predictable OTP, no expiry, no rate limit
const otp = Math.floor(Math.random() * 999999); // Not cryptographically secure
```

#### Verification Steps

- [ ] OTP generated with cryptographically secure randomness
- [ ] OTP hashed before storage (not plaintext)
- [ ] Short expiry (5-10 minutes)
- [ ] Rate limiting on OTP requests
- [ ] Maximum attempt limit per OTP
- [ ] One-time use (deleted after verification)

### 4. Mobile Biometric Authentication

#### Android BiometricPrompt

```kotlin
// PASS: CORRECT — Android BiometricPrompt for MFA
import androidx.biometric.BiometricPrompt
import androidx.biometric.BiometricManager

fun authenticateWithBiometric(
    activity: FragmentActivity,
    onSuccess: (BiometricPrompt.AuthenticationResult) -> Unit,
    onError: (String) -> Unit,
) {
    val biometricManager = BiometricManager.from(activity)
    when (biometricManager.canAuthenticate(BiometricManager.Authenticators.BIOMETRIC_STRONG)) {
        BiometricManager.BIOMETRIC_SUCCESS -> { /* Proceed */ }
        else -> { onError("Biometric not available"); return }
    }

    val promptInfo = BiometricPrompt.PromptInfo.Builder()
        .setTitle("Verify Identity")
        .setSubtitle("Use your fingerprint or face to continue")
        .setNegativeButtonText("Use PIN instead")
        .setAllowedAuthenticators(BiometricManager.Authenticators.BIOMETRIC_STRONG)
        .build()

    val biometricPrompt = BiometricPrompt(
        activity,
        ContextCompat.getMainExecutor(activity),
        object : BiometricPrompt.AuthenticationCallback() {
            override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult) {
                onSuccess(result)
            }
            override fun onAuthenticationError(errorCode: Int, errString: CharSequence) {
                onError(errString.toString())
            }
        }
    )

    biometricPrompt.authenticate(promptInfo)
}
```

#### iOS LAContext

```swift
// PASS: CORRECT — iOS biometric authentication
import LocalAuthentication

func authenticateWithBiometric() async throws -> Bool {
    let context = LAContext()
    context.localizedCancelTitle = "Use PIN instead"

    var error: NSError?
    guard context.canEvaluatePolicy(.deviceOwnerAuthenticationWithBiometrics, error: &error) else {
        throw AuthError.biometricNotAvailable(error?.localizedDescription ?? "Unknown")
    }

    return try await context.evaluatePolicy(
        .deviceOwnerAuthenticationWithBiometrics,
        localizedReason: "Verify your identity to continue"
    )
}

// Combine with server-side token refresh
func performMFAVerification() async throws {
    let biometricPassed = try await authenticateWithBiometric()
    guard biometricPassed else { throw AuthError.biometricFailed }

    // Exchange biometric proof for short-lived elevated token
    let elevatedToken = try await api.exchangeForElevatedToken(
        currentToken: tokenStore.accessToken,
        mfaMethod: "biometric"
    )
    tokenStore.setElevatedToken(elevatedToken)
}
```

#### Verification Steps

- [ ] Biometric check gates sensitive operations (not just login)
- [ ] Fallback to PIN/password when biometric unavailable
- [ ] Server-side records biometric verification event
- [ ] Biometric result tied to token elevation (not client-only)
- [ ] Device attestation accompanies biometric proof

### 5. MFA Recovery — Backup Codes

#### Backup Code Generation

```typescript
// PASS: CORRECT — One-time backup codes
import crypto from 'crypto';

async function generateBackupCodes(userId: string): Promise<string[]> {
  const codes: string[] = [];

  for (let i = 0; i < 10; i++) {
    const code = crypto.randomBytes(4).toString('hex'); // 8-char hex code
    codes.push(code);
  }

  // Store hashed codes
  const hashedCodes = await Promise.all(
    codes.map(async (code) => ({
      userId,
      hash: await bcrypt.hash(code, 10),
      used: false,
    })),
  );

  await db.backupCodes.deleteMany({ where: { userId } }); // Replace old codes
  await db.backupCodes.createMany({ data: hashedCodes });

  // Return plaintext codes ONCE for user to save
  return codes;
}

async function verifyBackupCode(userId: string, code: string): Promise<boolean> {
  const backupCodes = await db.backupCodes.findMany({
    where: { userId, used: false },
  });

  for (const bc of backupCodes) {
    if (await bcrypt.compare(code, bc.hash)) {
      await db.backupCodes.update({ where: { id: bc.id }, data: { used: true } });
      return true;
    }
  }

  return false;
}
```

#### Verification Steps

- [ ] 10 backup codes generated on MFA enrollment
- [ ] Codes shown only once, user prompted to save
- [ ] Codes hashed before storage
- [ ] Each code is one-time use
- [ ] Remaining code count shown to user
- [ ] New codes invalidate old set

## Pre-Deployment MFA Checklist

Before ANY production deployment with MFA:

- [ ] **TOTP**: Enrollment, verification, and secret encryption working
- [ ] **WebAuthn**: Registration and authentication flows tested
- [ ] **OTP**: Rate-limited, hashed, with expiry
- [ ] **Biometric**: Mobile biometric with server-side verification
- [ ] **Backup Codes**: Generated, hashed, one-time use
- [ ] **Recovery**: Account recovery flow tested (lost device scenario)
- [ ] **Enforcement**: MFA required for sensitive operations
- [ ] **Logging**: All MFA events logged for audit
- [ ] **Rate Limiting**: Brute force protection on all verification endpoints

## Resources

- [NIST SP 800-63B Digital Identity Guidelines](https://pages.nist.gov/800-63-3/sp800-63b.html)
- [WebAuthn Guide](https://webauthn.guide/)
- [SimpleWebAuthn Documentation](https://simplewebauthn.dev/)
- [OWASP MFA Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Multifactor_Authentication_Cheat_Sheet.html)

**Remember**: MFA is the single most effective defense against account takeover attacks. SMS OTP is better than no MFA, but TOTP and WebAuthn are significantly more secure. Always provide backup codes as a recovery mechanism.
