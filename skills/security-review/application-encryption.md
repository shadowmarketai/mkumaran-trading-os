| name | description |
|------|-------------|
| application-encryption | Use this skill when implementing field-level encryption, envelope encryption, key rotation, or managing encryption keys. Covers AES-256-GCM, CryptoKit, AndroidKeyStore, and cloud KMS integration. |

# Application Encryption Skill

This skill ensures sensitive data is properly encrypted at the application layer using field-level encryption, envelope encryption patterns, and proper key management.

## When to Activate

- Encrypting PII or sensitive fields in the database
- Implementing envelope encryption with cloud KMS
- Setting up encryption key rotation
- Storing encrypted data in mobile apps (Keychain, AndroidKeyStore)
- Implementing end-to-end encryption for user data
- Migrating from plaintext to encrypted storage

## Encryption Checklist

### 1. Field-Level Encryption (AES-256-GCM)

#### TypeScript Implementation

```typescript
// PASS: CORRECT — AES-256-GCM field-level encryption
import crypto from 'crypto';

const ALGORITHM = 'aes-256-gcm';
const IV_LENGTH = 12; // 96 bits for GCM
const TAG_LENGTH = 16; // 128 bits

interface EncryptedField {
  ciphertext: string; // base64
  iv: string;         // base64
  tag: string;        // base64
  version: number;    // key version for rotation
}

function encryptField(plaintext: string, key: Buffer): EncryptedField {
  const iv = crypto.randomBytes(IV_LENGTH);
  const cipher = crypto.createCipheriv(ALGORITHM, key, iv);

  let ciphertext = cipher.update(plaintext, 'utf8', 'base64');
  ciphertext += cipher.final('base64');
  const tag = cipher.getAuthTag();

  return {
    ciphertext,
    iv: iv.toString('base64'),
    tag: tag.toString('base64'),
    version: 1,
  };
}

function decryptField(encrypted: EncryptedField, key: Buffer): string {
  const decipher = crypto.createDecipheriv(
    ALGORITHM,
    key,
    Buffer.from(encrypted.iv, 'base64'),
  );
  decipher.setAuthTag(Buffer.from(encrypted.tag, 'base64'));

  let plaintext = decipher.update(encrypted.ciphertext, 'base64', 'utf8');
  plaintext += decipher.final('utf8');

  return plaintext;
}

// Usage with database model
async function createUser(data: { email: string; ssn: string }) {
  const key = await getEncryptionKey(); // From KMS or env

  return db.users.create({
    data: {
      email: data.email, // Not encrypted (needed for lookup)
      emailHash: hashForLookup(data.email), // HMAC for searching
      ssnEncrypted: JSON.stringify(encryptField(data.ssn, key)),
    },
  });
}

// FAIL: WRONG — Using ECB mode, no authentication
const cipher = crypto.createCipheriv('aes-256-ecb', key, null); // No IV, no auth tag
// FAIL: WRONG — Using MD5 for key derivation
const key = crypto.createHash('md5').update(password).digest();
```

#### Python Implementation

```python
# PASS: CORRECT — Python AES-256-GCM with cryptography library
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.fernet import Fernet
import os
import base64
import json

class FieldEncryptor:
    """AES-256-GCM field-level encryption."""

    def __init__(self, key: bytes):
        if len(key) != 32:
            raise ValueError("Key must be 32 bytes for AES-256")
        self._aesgcm = AESGCM(key)

    def encrypt(self, plaintext: str) -> dict:
        nonce = os.urandom(12)  # 96-bit nonce
        ciphertext = self._aesgcm.encrypt(
            nonce, plaintext.encode("utf-8"), None
        )
        return {
            "ciphertext": base64.b64encode(ciphertext).decode(),
            "nonce": base64.b64encode(nonce).decode(),
            "version": 1,
        }

    def decrypt(self, encrypted: dict) -> str:
        nonce = base64.b64decode(encrypted["nonce"])
        ciphertext = base64.b64decode(encrypted["ciphertext"])
        plaintext = self._aesgcm.decrypt(nonce, ciphertext, None)
        return plaintext.decode("utf-8")

# Alternative: Fernet (simpler, includes timestamp and HMAC)
class FernetEncryptor:
    """Fernet symmetric encryption — simpler API, includes authentication."""

    def __init__(self, key: bytes | None = None):
        self._fernet = Fernet(key or Fernet.generate_key())

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, token: str) -> str:
        return self._fernet.decrypt(token.encode()).decode()

# FAIL: WRONG — Using DES, no authentication
from Crypto.Cipher import DES  # Deprecated, weak
```

#### Verification Steps

- [ ] AES-256-GCM used (authenticated encryption)
- [ ] Unique IV/nonce per encryption operation
- [ ] Authentication tag verified on decryption
- [ ] Key stored securely (KMS, env var, not in code)
- [ ] Encrypted fields identifiable in schema (naming convention)
- [ ] Searchable fields use separate HMAC hash column

### 2. Envelope Encryption with Cloud KMS

#### AWS KMS Envelope Encryption

```typescript
// PASS: CORRECT — Envelope encryption pattern
import { KMSClient, GenerateDataKeyCommand, DecryptCommand } from '@aws-sdk/client-kms';

const kms = new KMSClient({ region: 'us-east-1' });

interface EnvelopeEncrypted {
  encryptedDataKey: string; // base64 — encrypted by KMS
  ciphertext: string;       // base64 — encrypted by data key
  iv: string;
  tag: string;
  kmsKeyId: string;
}

async function envelopeEncrypt(plaintext: string): Promise<EnvelopeEncrypted> {
  // 1. Generate data key from KMS
  const { Plaintext: dataKey, CiphertextBlob: encryptedDataKey } = await kms.send(
    new GenerateDataKeyCommand({
      KeyId: process.env.KMS_KEY_ID!,
      KeySpec: 'AES_256',
    }),
  );

  // 2. Encrypt data locally with data key
  const iv = crypto.randomBytes(12);
  const cipher = crypto.createCipheriv('aes-256-gcm', dataKey!, iv);
  let ciphertext = cipher.update(plaintext, 'utf8', 'base64');
  ciphertext += cipher.final('base64');
  const tag = cipher.getAuthTag();

  // 3. Zero out plaintext data key from memory
  dataKey!.fill(0);

  return {
    encryptedDataKey: Buffer.from(encryptedDataKey!).toString('base64'),
    ciphertext,
    iv: iv.toString('base64'),
    tag: tag.toString('base64'),
    kmsKeyId: process.env.KMS_KEY_ID!,
  };
}

async function envelopeDecrypt(encrypted: EnvelopeEncrypted): Promise<string> {
  // 1. Decrypt data key via KMS
  const { Plaintext: dataKey } = await kms.send(
    new DecryptCommand({
      CiphertextBlob: Buffer.from(encrypted.encryptedDataKey, 'base64'),
    }),
  );

  // 2. Decrypt data locally
  const decipher = crypto.createDecipheriv(
    'aes-256-gcm',
    dataKey!,
    Buffer.from(encrypted.iv, 'base64'),
  );
  decipher.setAuthTag(Buffer.from(encrypted.tag, 'base64'));

  let plaintext = decipher.update(encrypted.ciphertext, 'base64', 'utf8');
  plaintext += decipher.final('utf8');

  // 3. Zero out data key
  dataKey!.fill(0);

  return plaintext;
}
```

#### Verification Steps

- [ ] Data encryption key (DEK) generated per record or batch
- [ ] DEK encrypted by KMS master key (KEK)
- [ ] Plaintext DEK zeroed from memory after use
- [ ] KMS key ID stored with encrypted data for key rotation
- [ ] KMS access controlled by IAM policies
- [ ] KMS audit logging enabled

### 3. Key Rotation

#### Rotation Strategy

```typescript
// PASS: CORRECT — Key rotation with version tracking
interface KeyVersion {
  version: number;
  key: Buffer;
  createdAt: Date;
  status: 'active' | 'decrypt-only' | 'retired';
}

class KeyManager {
  private keys: Map<number, KeyVersion> = new Map();

  async rotateKey(): Promise<void> {
    const currentVersion = this.getActiveKey().version;
    const newVersion = currentVersion + 1;

    // 1. Generate new key
    const newKey = crypto.randomBytes(32);

    // 2. Mark current key as decrypt-only
    const current = this.keys.get(currentVersion)!;
    current.status = 'decrypt-only';

    // 3. Register new active key
    this.keys.set(newVersion, {
      version: newVersion,
      key: newKey,
      createdAt: new Date(),
      status: 'active',
    });

    // 4. Re-encrypt data in background (optional, for forward secrecy)
    await this.scheduleReEncryption(currentVersion, newVersion);
  }

  encrypt(plaintext: string): EncryptedField {
    const active = this.getActiveKey();
    const result = encryptField(plaintext, active.key);
    result.version = active.version;
    return result;
  }

  decrypt(encrypted: EncryptedField): string {
    const key = this.keys.get(encrypted.version);
    if (!key || key.status === 'retired') {
      throw new Error(`Key version ${encrypted.version} not available`);
    }
    return decryptField(encrypted, key.key);
  }
}
```

#### Verification Steps

- [ ] Key version tracked with every encrypted field
- [ ] Old keys retained for decryption (decrypt-only status)
- [ ] New encryptions always use active key
- [ ] Key rotation automated (quarterly or on demand)
- [ ] Re-encryption of old data scheduled after rotation
- [ ] Retired keys securely destroyed after re-encryption

### 4. Mobile Encryption — Android KeyStore

```kotlin
// PASS: CORRECT — AndroidKeyStore for sensitive data
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

object SecureEncryptor {
    private const val KEY_ALIAS = "app_encryption_key"
    private const val TRANSFORMATION = "AES/GCM/NoPadding"
    private const val TAG_LENGTH = 128

    fun getOrCreateKey(): SecretKey {
        val keyStore = java.security.KeyStore.getInstance("AndroidKeyStore").apply { load(null) }

        keyStore.getKey(KEY_ALIAS, null)?.let { return it as SecretKey }

        val keyGenerator = KeyGenerator.getInstance(
            KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore"
        )
        keyGenerator.init(
            KeyGenParameterSpec.Builder(
                KEY_ALIAS,
                KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT
            )
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256)
                .setUserAuthenticationRequired(false) // Set true for biometric-gated
                .build()
        )
        return keyGenerator.generateKey()
    }

    fun encrypt(plaintext: ByteArray): Pair<ByteArray, ByteArray> {
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, getOrCreateKey())
        val ciphertext = cipher.doFinal(plaintext)
        return Pair(cipher.iv, ciphertext) // Store IV alongside ciphertext
    }

    fun decrypt(iv: ByteArray, ciphertext: ByteArray): ByteArray {
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.DECRYPT_MODE, getOrCreateKey(), GCMParameterSpec(TAG_LENGTH, iv))
        return cipher.doFinal(ciphertext)
    }
}
```

### 5. Mobile Encryption — iOS CryptoKit & Keychain

```swift
// PASS: CORRECT — CryptoKit AES-GCM and Keychain storage
import CryptoKit
import Foundation

struct SecureEncryptor {
    /// Generate or retrieve encryption key from Keychain
    static func getOrCreateKey() throws -> SymmetricKey {
        let tag = "com.myapp.encryption.key"

        // Try to retrieve from Keychain
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrAccount as String: tag,
            kSecReturnData as String: true,
        ]

        var result: AnyObject?
        let status = SecItemCopyMatching(query as CFDictionary, &result)

        if status == errSecSuccess, let data = result as? Data {
            return SymmetricKey(data: data)
        }

        // Generate new key
        let key = SymmetricKey(size: .bits256)
        let keyData = key.withUnsafeBytes { Data($0) }

        let addQuery: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrAccount as String: tag,
            kSecValueData as String: keyData,
            kSecAttrAccessible as String: kSecAttrAccessibleWhenUnlockedThisDeviceOnly,
        ]
        SecItemAdd(addQuery as CFDictionary, nil)

        return key
    }

    /// Encrypt data with AES-GCM
    static func encrypt(_ data: Data) throws -> Data {
        let key = try getOrCreateKey()
        let sealedBox = try AES.GCM.seal(data, using: key)
        return sealedBox.combined! // nonce + ciphertext + tag
    }

    /// Decrypt data with AES-GCM
    static func decrypt(_ combined: Data) throws -> Data {
        let key = try getOrCreateKey()
        let sealedBox = try AES.GCM.SealedBox(combined: combined)
        return try AES.GCM.open(sealedBox, using: key)
    }
}
```

#### Verification Steps (Mobile)

- [ ] Hardware-backed keystore used (AndroidKeyStore / Secure Enclave)
- [ ] AES-256-GCM for all encryption operations
- [ ] Keys scoped to device (kSecAttrAccessibleWhenUnlockedThisDeviceOnly)
- [ ] Biometric gating for high-sensitivity keys (optional)
- [ ] Keys not exportable from hardware keystore
- [ ] Encrypted data cleared on app uninstall (if appropriate)

## Pre-Deployment Encryption Checklist

Before ANY production deployment with encrypted data:

- [ ] **Algorithm**: AES-256-GCM (authenticated encryption) used everywhere
- [ ] **Key Management**: Keys in KMS or hardware keystore, never in code
- [ ] **Envelope Encryption**: DEK/KEK pattern for database fields
- [ ] **IV/Nonce**: Unique per encryption operation, never reused
- [ ] **Key Rotation**: Version tracking enabled, rotation procedure tested
- [ ] **Mobile**: Hardware-backed keystores on both platforms
- [ ] **At Rest**: Sensitive database fields encrypted
- [ ] **In Transit**: TLS 1.2+ enforced
- [ ] **Key Zeroing**: Plaintext keys cleared from memory after use
- [ ] **Audit**: Key access and rotation events logged

## Resources

- [NIST SP 800-38D — GCM Recommendation](https://csrc.nist.gov/publications/detail/sp/800-38d/final)
- [AWS KMS Best Practices](https://docs.aws.amazon.com/kms/latest/developerguide/best-practices.html)
- [Apple CryptoKit Documentation](https://developer.apple.com/documentation/cryptokit)
- [Android Keystore System](https://developer.android.com/training/articles/keystore)
- [OWASP Cryptographic Storage Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Cryptographic_Storage_Cheat_Sheet.html)

**Remember**: Encryption without proper key management is security theater. The algorithm is the easy part — protecting and rotating keys is where most implementations fail. Use cloud KMS or hardware keystores, never roll your own key management.
