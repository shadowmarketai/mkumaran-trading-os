| name | description |
|------|-------------|
| zero-trust-architecture | Use this skill when implementing service-to-service authentication, mTLS, device trust, identity mesh, or attribute-based access control. Ensures Zero Trust Architecture principles throughout the stack. |

# Zero Trust Architecture Skill

This skill ensures all systems follow Zero Trust principles: never trust, always verify — regardless of network location.

## When to Activate

- Implementing service-to-service communication
- Configuring API gateways or reverse proxies
- Setting up mutual TLS (mTLS) between services
- Implementing device trust or posture checking
- Designing identity mesh or identity-aware proxies
- Implementing attribute-based access control (ABAC)
- Configuring network micro-segmentation
- Setting up continuous verification workflows

## Zero Trust Checklist

### 1. Continuous Verification

#### Every Request Verified

```typescript
// PASS: CORRECT — Verify identity, device, and context on every request
import { verifyToken, checkDeviceTrust, evaluatePolicy } from '@/lib/zero-trust';

async function zeroTrustMiddleware(req: Request, next: () => Promise<Response>) {
  // 1. Verify identity (JWT/session)
  const identity = await verifyToken(req.headers.get('Authorization'));
  if (!identity) return new Response('Unauthorized', { status: 401 });

  // 2. Verify device posture
  const deviceId = req.headers.get('X-Device-ID');
  const deviceTrust = await checkDeviceTrust(deviceId, identity.userId);
  if (!deviceTrust.trusted) return new Response('Device not trusted', { status: 403 });

  // 3. Evaluate access policy (ABAC)
  const allowed = await evaluatePolicy({
    subject: identity,
    resource: req.url,
    action: req.method,
    context: {
      ip: req.headers.get('X-Forwarded-For'),
      deviceTrust: deviceTrust.level,
      time: new Date(),
      riskScore: await calculateRiskScore(identity, req),
    },
  });

  if (!allowed) return new Response('Access denied by policy', { status: 403 });

  return next();
}

// FAIL: WRONG — Trust based on network location
if (req.ip.startsWith('10.0.')) {
  // Internal network = trusted — NEVER do this
  return next();
}
```

```python
# PASS: CORRECT — FastAPI Zero Trust middleware
from fastapi import Request, HTTPException, Depends
from app.zero_trust import verify_identity, check_device, evaluate_policy

async def zero_trust_guard(request: Request):
    # Verify identity
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    identity = await verify_identity(token)
    if not identity:
        raise HTTPException(status_code=401, detail="Identity verification failed")

    # Verify device
    device_id = request.headers.get("X-Device-ID")
    if not await check_device(device_id, identity.user_id):
        raise HTTPException(status_code=403, detail="Device not trusted")

    # Evaluate policy
    decision = await evaluate_policy(
        subject=identity,
        resource=str(request.url),
        action=request.method,
        context={"ip": request.client.host},
    )
    if not decision.allowed:
        raise HTTPException(status_code=403, detail="Policy denied")

    return identity
```

#### Verification Steps

- [ ] Identity verified on every request (not just at login)
- [ ] No implicit trust based on network location
- [ ] Session validity checked continuously
- [ ] Token expiry enforced (short-lived tokens preferred)
- [ ] Re-authentication required for sensitive operations

### 2. Mutual TLS (mTLS)

#### Service-to-Service mTLS

```typescript
// PASS: CORRECT — mTLS between services
import https from 'https';
import fs from 'fs';

const agent = new https.Agent({
  cert: fs.readFileSync('/certs/client.crt'),
  key: fs.readFileSync('/certs/client.key'),
  ca: fs.readFileSync('/certs/ca.crt'),
  rejectUnauthorized: true, // Verify server certificate
});

const response = await fetch('https://payment-service.internal:8443/api/charge', {
  method: 'POST',
  agent,
  body: JSON.stringify({ amount: 1000 }),
});

// FAIL: WRONG — Disabling certificate verification
const agent = new https.Agent({ rejectUnauthorized: false }); // NEVER
```

```python
# PASS: CORRECT — Python mTLS client
import httpx

client = httpx.AsyncClient(
    cert=("/certs/client.crt", "/certs/client.key"),
    verify="/certs/ca.crt",
)

response = await client.post(
    "https://payment-service.internal:8443/api/charge",
    json={"amount": 1000},
)

# FAIL: WRONG — Disabling SSL verification
response = httpx.post(url, verify=False)  # NEVER
```

#### Kubernetes mTLS with Service Mesh

```yaml
# PASS: CORRECT — Istio mTLS policy
apiVersion: security.istio.io/v1beta1
kind: PeerAuthentication
metadata:
  name: default
  namespace: production
spec:
  mtls:
    mode: STRICT  # All traffic must be mTLS

---
# Authorization policy — only payment-service can call billing-service
apiVersion: security.istio.io/v1beta1
kind: AuthorizationPolicy
metadata:
  name: billing-service-policy
  namespace: production
spec:
  selector:
    matchLabels:
      app: billing-service
  rules:
    - from:
        - source:
            principals: ["cluster.local/ns/production/sa/payment-service"]
      to:
        - operation:
            methods: ["POST"]
            paths: ["/api/charge"]
```

#### Verification Steps

- [ ] mTLS enabled between all internal services
- [ ] Certificate rotation automated
- [ ] No services using plain HTTP internally
- [ ] Certificate pinning for critical service pairs
- [ ] Service mesh (Istio/Linkerd) configured for mTLS enforcement

### 3. Device Trust

#### Device Registration & Posture

```typescript
// PASS: CORRECT — Device trust assessment
interface DevicePosture {
  deviceId: string;
  osVersion: string;
  encryptionEnabled: boolean;
  screenLockEnabled: boolean;
  jailbroken: boolean;
  lastSeen: Date;
  trustLevel: 'high' | 'medium' | 'low' | 'untrusted';
}

function assessDeviceTrust(posture: DevicePosture): DeviceTrustResult {
  // Reject jailbroken/rooted devices
  if (posture.jailbroken) return { trusted: false, reason: 'jailbroken' };

  // Require encryption
  if (!posture.encryptionEnabled) return { trusted: false, reason: 'no_encryption' };

  // Require screen lock
  if (!posture.screenLockEnabled) return { trusted: false, reason: 'no_screen_lock' };

  // Check OS currency
  if (isOSOutdated(posture.osVersion)) {
    return { trusted: true, level: 'medium', reason: 'outdated_os' };
  }

  return { trusted: true, level: 'high' };
}
```

```kotlin
// PASS: CORRECT — Android device attestation
import com.google.android.gms.safetynet.SafetyNet

suspend fun attestDevice(context: Context, nonce: String): DeviceAttestation {
    val result = SafetyNet.getClient(context)
        .attest(nonce.toByteArray(), BuildConfig.SAFETY_NET_API_KEY)
        .await()

    return DeviceAttestation(
        token = result.jwsResult,
        isBasicIntegrity = true,
        isCtsProfileMatch = true,
    )
}
```

#### Verification Steps

- [ ] Device registration required before access
- [ ] Device posture checked on each request (or periodically)
- [ ] Jailbroken/rooted devices blocked or restricted
- [ ] Device encryption verified
- [ ] Lost/stolen device revocation supported

### 4. Attribute-Based Access Control (ABAC)

#### Policy Engine

```typescript
// PASS: CORRECT — ABAC policy evaluation
interface AccessPolicy {
  id: string;
  effect: 'allow' | 'deny';
  conditions: PolicyCondition[];
}

interface PolicyCondition {
  attribute: string;
  operator: 'equals' | 'in' | 'gte' | 'lte' | 'between';
  value: unknown;
}

function evaluateABAC(
  policies: AccessPolicy[],
  context: Record<string, unknown>,
): boolean {
  // Deny by default
  let allowed = false;

  for (const policy of policies) {
    const matches = policy.conditions.every((cond) =>
      evaluateCondition(cond, context),
    );

    if (matches) {
      if (policy.effect === 'deny') return false; // Explicit deny wins
      allowed = true;
    }
  }

  return allowed;
}

// Example policy: Allow finance team to access billing during business hours
const billingPolicy: AccessPolicy = {
  id: 'billing-access',
  effect: 'allow',
  conditions: [
    { attribute: 'user.department', operator: 'equals', value: 'finance' },
    { attribute: 'user.role', operator: 'in', value: ['admin', 'billing_manager'] },
    { attribute: 'context.hour', operator: 'between', value: [9, 17] },
    { attribute: 'device.trustLevel', operator: 'in', value: ['high', 'medium'] },
  ],
};
```

#### Verification Steps

- [ ] Access policies use multiple attributes (role, department, time, device, location)
- [ ] Explicit deny overrides allow
- [ ] Policies stored externally (not hardcoded)
- [ ] Policy changes audited
- [ ] Default deny when no policy matches

### 5. Micro-Segmentation

#### Network Policies

```yaml
# PASS: CORRECT — Kubernetes NetworkPolicy
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: api-server-policy
  namespace: production
spec:
  podSelector:
    matchLabels:
      app: api-server
  policyTypes:
    - Ingress
    - Egress
  ingress:
    - from:
        - podSelector:
            matchLabels:
              app: api-gateway
      ports:
        - port: 8080
  egress:
    - to:
        - podSelector:
            matchLabels:
              app: database
      ports:
        - port: 5432
    - to:
        - podSelector:
            matchLabels:
              app: cache
      ports:
        - port: 6379
```

#### Verification Steps

- [ ] Network policies enforce least-privilege communication
- [ ] Each service can only reach services it depends on
- [ ] Database accessible only from application tier
- [ ] Egress traffic restricted and monitored
- [ ] East-west traffic encrypted (mTLS)

### 6. Identity Mesh

#### Unified Identity Across Services

```typescript
// PASS: CORRECT — Propagate identity context through service calls
interface IdentityContext {
  userId: string;
  roles: string[];
  deviceId: string;
  sessionId: string;
  trustLevel: string;
  originService: string;
  requestChain: string[]; // Trace of services in the call chain
}

async function callDownstreamService(
  url: string,
  identity: IdentityContext,
  payload: unknown,
) {
  const updatedChain = [...identity.requestChain, 'current-service'];

  return fetch(url, {
    method: 'POST',
    headers: {
      'X-Identity-Token': await signIdentityToken(identity),
      'X-Request-Chain': updatedChain.join(','),
      'X-Correlation-ID': identity.sessionId,
    },
    body: JSON.stringify(payload),
  });
}
```

#### Verification Steps

- [ ] Identity propagated across service boundaries
- [ ] Service-level identity (service accounts) distinct from user identity
- [ ] Identity tokens signed and verified at each hop
- [ ] Request tracing enabled across service mesh
- [ ] No privilege escalation through service chains

## Pre-Deployment Zero Trust Checklist

Before ANY production deployment:

- [ ] **Verify Everything**: No implicit trust based on network, IP, or location
- [ ] **mTLS**: All service-to-service communication uses mutual TLS
- [ ] **Device Trust**: Device posture checked before access granted
- [ ] **ABAC**: Fine-grained policies beyond simple role checks
- [ ] **Micro-Segmentation**: Network policies restrict lateral movement
- [ ] **Identity Mesh**: Identity context propagated across service calls
- [ ] **Short-Lived Tokens**: JWT expiry under 15 minutes, refresh tokens rotated
- [ ] **Continuous Monitoring**: Anomalous access patterns trigger alerts
- [ ] **Least Privilege**: Each service has minimum required permissions
- [ ] **Audit Trail**: All access decisions logged for forensic analysis

## Resources

- [NIST SP 800-207 Zero Trust Architecture](https://csrc.nist.gov/publications/detail/sp/800-207/final)
- [Google BeyondCorp](https://cloud.google.com/beyondcorp)
- [CISA Zero Trust Maturity Model](https://www.cisa.gov/zero-trust-maturity-model)
- [Istio Security Documentation](https://istio.io/latest/docs/concepts/security/)

**Remember**: Zero Trust means "never trust, always verify." Every request must prove its identity, device posture, and authorization — regardless of where it originates. The network perimeter is not a trust boundary.
