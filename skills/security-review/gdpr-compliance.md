| name | description |
|------|-------------|
| gdpr-compliance | Use this skill when handling personal data, implementing consent mechanisms, building data export/erasure features, or conducting Data Protection Impact Assessments. Ensures GDPR compliance across web, API, and mobile layers. |

# GDPR Compliance Skill

This skill ensures all personal data handling complies with the General Data Protection Regulation (GDPR) and related privacy frameworks.

## When to Activate

- Collecting or processing personal data (name, email, IP, cookies)
- Implementing user registration or profile features
- Building consent management (cookie banners, marketing opt-in)
- Implementing data export (portability) or deletion (right to erasure)
- Conducting a Data Protection Impact Assessment (DPIA)
- Handling data breach notification workflows
- Integrating third-party analytics, ads, or tracking
- Storing data across jurisdictions (EU data residency)

## GDPR Compliance Checklist

### 1. Lawful Basis & Consent

#### Consent Collection

```typescript
// PASS: CORRECT — Explicit, granular, revocable consent
interface ConsentRecord {
  userId: string;
  purpose: 'marketing' | 'analytics' | 'personalization';
  granted: boolean;
  timestamp: Date;
  ipAddress: string;
  version: string; // consent policy version
}

async function recordConsent(consent: ConsentRecord): Promise<void> {
  await db.consents.create({
    data: {
      ...consent,
      timestamp: new Date(),
      expiresAt: addMonths(new Date(), 12), // re-consent annually
    },
  });
}

// FAIL: WRONG — Pre-checked boxes, bundled consent
const consent = true; // assumed consent
```

```python
# PASS: CORRECT — Django/FastAPI consent model
from datetime import datetime, timedelta
from sqlalchemy import Column, String, Boolean, DateTime
from app.database import Base

class ConsentRecord(Base):
    __tablename__ = "consent_records"

    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False, index=True)
    purpose = Column(String, nullable=False)  # 'marketing', 'analytics'
    granted = Column(Boolean, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    ip_address = Column(String, nullable=False)
    policy_version = Column(String, nullable=False)
    expires_at = Column(DateTime, default=lambda: datetime.utcnow() + timedelta(days=365))

# FAIL: WRONG — No audit trail for consent
user.marketing_emails = True  # No timestamp, no IP, no version
```

#### Verification Steps

- [ ] Consent is explicit, not pre-checked or bundled
- [ ] Each processing purpose has separate consent
- [ ] Consent records include timestamp, IP, policy version
- [ ] Users can withdraw consent as easily as they gave it
- [ ] Consent is re-requested after policy changes
- [ ] Lawful basis documented for each data processing activity

### 2. Right to Erasure (Right to Be Forgotten)

#### Data Deletion Pipeline

```typescript
// PASS: CORRECT — Comprehensive erasure with audit
async function eraseUserData(userId: string): Promise<ErasureReport> {
  const report: ErasureReport = { userId, deletedAt: new Date(), systems: [] };

  await db.$transaction(async (tx) => {
    // 1. Delete personal data from primary tables
    await tx.users.delete({ where: { id: userId } });
    report.systems.push('users');

    // 2. Delete from related tables
    await tx.profiles.deleteMany({ where: { userId } });
    report.systems.push('profiles');

    // 3. Anonymize data that must be retained (e.g., order history)
    await tx.orders.updateMany({
      where: { userId },
      data: { userId: 'ANONYMIZED', email: 'deleted@anonymized.local' },
    });
    report.systems.push('orders_anonymized');

    // 4. Delete from external systems
    await stripeClient.customers.del(userId);
    report.systems.push('stripe');

    await analyticsClient.deleteUser(userId);
    report.systems.push('analytics');
  });

  // 5. Log erasure (without PII)
  await auditLog.create({
    action: 'GDPR_ERASURE',
    targetId: hashUserId(userId),
    systems: report.systems,
    completedAt: new Date(),
  });

  return report;
}

// FAIL: WRONG — Soft delete only, data still exists
await db.users.update({ where: { id: userId }, data: { deleted: true } });
```

```python
# PASS: CORRECT — Python erasure service
async def erase_user_data(user_id: str, db: AsyncSession) -> dict:
    report = {"user_id_hash": hashlib.sha256(user_id.encode()).hexdigest(), "systems": []}

    # Delete from primary tables
    await db.execute(delete(User).where(User.id == user_id))
    report["systems"].append("users")

    # Anonymize retained records
    await db.execute(
        update(Order)
        .where(Order.user_id == user_id)
        .values(user_id="ANONYMIZED", email="deleted@anonymized.local")
    )
    report["systems"].append("orders_anonymized")

    await db.commit()
    return report
```

#### Verification Steps

- [ ] All personal data deletable within 30 days
- [ ] Related records in all tables handled (delete or anonymize)
- [ ] External systems included (Stripe, analytics, email providers)
- [ ] Audit log records erasure without storing PII
- [ ] Backups have retention policy (data eventually purged)
- [ ] Erasure request confirmation sent to user

### 3. Right to Data Portability

#### Data Export

```typescript
// PASS: CORRECT — Machine-readable JSON export
async function exportUserData(userId: string): Promise<PortabilityPackage> {
  const user = await db.users.findUnique({
    where: { id: userId },
    include: { profile: true, orders: true, preferences: true },
  });

  const package_: PortabilityPackage = {
    exportedAt: new Date().toISOString(),
    format: 'GDPR-portability-v1',
    data: {
      personal: {
        name: user.name,
        email: user.email,
        phone: user.phone,
        createdAt: user.createdAt,
      },
      profile: user.profile,
      orders: user.orders.map((o) => ({
        id: o.id,
        date: o.createdAt,
        total: o.total,
        items: o.items,
      })),
      preferences: user.preferences,
      consents: await db.consents.findMany({ where: { userId } }),
    },
  };

  return package_;
}
```

#### Verification Steps

- [ ] Export in machine-readable format (JSON or CSV)
- [ ] All personal data categories included
- [ ] Export delivered securely (encrypted download link)
- [ ] Export completed within 30 days of request
- [ ] Export does not include other users' data

### 4. Data Protection Impact Assessment (DPIA)

#### DPIA Trigger Checklist

```markdown
A DPIA is REQUIRED when processing involves:
- [ ] Large-scale processing of sensitive data
- [ ] Systematic monitoring of public areas
- [ ] Automated decision-making with legal effects
- [ ] Large-scale profiling
- [ ] Processing of children's data
- [ ] Cross-border data transfers
- [ ] New technology with unknown privacy impact
```

#### DPIA Template

```typescript
interface DPIA {
  projectName: string;
  assessor: string;
  date: Date;
  dataFlows: DataFlow[];
  risks: Risk[];
  mitigations: Mitigation[];
  residualRisk: 'low' | 'medium' | 'high';
  dpoApproval: boolean;
}

interface DataFlow {
  dataCategory: string;         // e.g., 'email', 'payment_info'
  source: string;               // e.g., 'user_registration_form'
  purpose: string;              // e.g., 'account_creation'
  lawfulBasis: string;          // e.g., 'consent', 'contract'
  retention: string;            // e.g., '2 years after account deletion'
  recipients: string[];         // e.g., ['Stripe', 'SendGrid']
  crossBorderTransfer: boolean;
}
```

#### Verification Steps

- [ ] DPIA conducted before high-risk processing begins
- [ ] All data flows mapped with lawful basis
- [ ] Risks identified and mitigations documented
- [ ] DPO consulted and approval recorded
- [ ] DPIA reviewed annually or when processing changes

### 5. Breach Notification

#### Breach Response Workflow

```typescript
// PASS: CORRECT — Automated breach notification pipeline
interface BreachNotification {
  detectedAt: Date;
  nature: string;
  dataCategories: string[];
  approximateRecords: number;
  consequences: string;
  measuresTaken: string[];
}

async function handleDataBreach(breach: BreachNotification): Promise<void> {
  // 1. Log breach internally (within 24 hours)
  await incidentLog.create({ ...breach, status: 'detected' });

  // 2. Assess severity
  const isHighRisk = breach.dataCategories.some((c) =>
    ['payment', 'health', 'biometric'].includes(c)
  );

  // 3. Notify supervisory authority within 72 hours
  if (isHighRisk) {
    await notifyDPA({
      breach,
      reportedAt: new Date(),
      dpoContact: process.env.DPO_EMAIL,
    });
  }

  // 4. Notify affected users if high risk to rights/freedoms
  if (isHighRisk) {
    await notifyAffectedUsers(breach);
  }

  // 5. Document everything
  await incidentLog.update({
    breachId: breach.id,
    status: 'notified',
    notifiedAt: new Date(),
  });
}
```

#### Verification Steps

- [ ] Breach detection mechanisms in place
- [ ] Internal notification within 24 hours
- [ ] Supervisory authority notified within 72 hours (if required)
- [ ] Affected users notified without undue delay (if high risk)
- [ ] Breach register maintained with all incidents
- [ ] Post-breach review and remediation documented

### 6. Privacy by Design

#### Data Minimization

```typescript
// PASS: CORRECT — Collect only what's needed
const registrationSchema = z.object({
  email: z.string().email(),
  password: z.string().min(8),
  // Only collect name if strictly necessary
});

// FAIL: WRONG — Collecting unnecessary data
const registrationSchema = z.object({
  email: z.string().email(),
  password: z.string().min(8),
  phone: z.string(),          // Not needed for registration
  dateOfBirth: z.date(),       // Not needed for registration
  socialSecurity: z.string(),  // NEVER collect unless legally required
});
```

#### Data Retention

```typescript
// PASS: CORRECT — Automated retention enforcement
const RETENTION_POLICIES = {
  user_data: { months: 24, action: 'anonymize' },
  access_logs: { months: 6, action: 'delete' },
  consent_records: { months: 60, action: 'archive' }, // Keep for proof
  payment_records: { months: 84, action: 'archive' }, // 7 years for tax
} as const;

async function enforceRetention(): Promise<void> {
  for (const [category, policy] of Object.entries(RETENTION_POLICIES)) {
    const cutoff = subMonths(new Date(), policy.months);
    if (policy.action === 'delete') {
      await db[category].deleteMany({ where: { createdAt: { lt: cutoff } } });
    } else if (policy.action === 'anonymize') {
      await anonymizeRecords(category, cutoff);
    }
  }
}
```

#### Verification Steps

- [ ] Only necessary data collected (data minimization)
- [ ] Retention periods defined for all data categories
- [ ] Automated retention enforcement in place
- [ ] Purpose limitation enforced (data used only for stated purpose)
- [ ] Storage limitation enforced (data not kept longer than needed)

## Pre-Deployment GDPR Checklist

Before ANY production deployment handling EU personal data:

- [ ] **Lawful Basis**: Documented for each processing activity
- [ ] **Consent**: Explicit, granular, revocable, with audit trail
- [ ] **Privacy Policy**: Clear, accessible, covers all processing
- [ ] **Right to Erasure**: Complete deletion pipeline tested
- [ ] **Right to Portability**: JSON/CSV export working
- [ ] **DPIA**: Conducted for high-risk processing
- [ ] **Breach Notification**: 72-hour pipeline tested
- [ ] **Data Minimization**: Only necessary data collected
- [ ] **Retention**: Automated enforcement configured
- [ ] **Cross-Border**: Adequate safeguards for international transfers
- [ ] **DPO**: Designated if required (public authority, large-scale processing)
- [ ] **Records of Processing**: Article 30 records maintained

## Resources

- [GDPR Full Text](https://gdpr-info.eu/)
- [ICO Guide to GDPR](https://ico.org.uk/for-organisations/guide-to-data-protection/guide-to-the-general-data-protection-regulation-gdpr/)
- [EDPB Guidelines](https://edpb.europa.eu/our-work-tools/general-guidance_en)
- [OWASP Privacy by Design](https://owasp.org/www-project-top-10-privacy-risks/)

**Remember**: GDPR non-compliance can result in fines up to 4% of annual global turnover or EUR 20 million. Privacy must be built in from the start, not bolted on after launch.
