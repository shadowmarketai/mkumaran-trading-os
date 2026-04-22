| name | description |
|------|-------------|
| dast-pen-testing | Use this skill when performing dynamic application security testing, running OWASP ZAP or Nuclei scans, conducting API security tests, or following penetration testing methodology. Provides DAST automation and pen test workflows. |

# DAST & Penetration Testing Skill

This skill provides dynamic application security testing (DAST) automation, API security testing patterns, and penetration testing methodology for web and mobile applications.

## When to Activate

- Running automated security scans against running applications
- Conducting API security testing
- Setting up DAST in CI/CD pipelines
- Performing penetration testing (with authorization)
- Validating security fixes with active scanning
- Testing for runtime vulnerabilities not caught by SAST

## DAST Checklist

### 1. OWASP ZAP Automation

#### ZAP Baseline Scan

```yaml
# PASS: CORRECT — ZAP baseline scan in CI/CD
# .github/workflows/dast.yml
name: DAST Security Scan
on:
  schedule:
    - cron: '0 2 * * 1'  # Weekly Monday 2 AM
  workflow_dispatch:

jobs:
  zap-scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Start application
        run: docker-compose up -d
        env:
          NODE_ENV: test

      - name: Wait for app to be ready
        run: |
          for i in $(seq 1 30); do
            curl -s http://localhost:3000/health && break
            sleep 2
          done

      - name: ZAP Baseline Scan
        uses: zaproxy/action-baseline@v0.12.0
        with:
          target: 'http://localhost:3000'
          rules_file_name: '.zap/rules.tsv'
          cmd_options: '-a -j'

      - name: Upload ZAP Report
        uses: actions/upload-artifact@v4
        if: always()
        with:
          name: zap-report
          path: report_html.html
```

#### ZAP Rules Configuration

```tsv
# .zap/rules.tsv — Customize alert thresholds
# Rule ID	Action	Description
10003	IGNORE	Vulnerable JS Library (handled by npm audit)
10015	WARN	Incomplete or No Cache-control Header
10021	FAIL	X-Content-Type-Options Header Missing
10038	FAIL	Content Security Policy Header Not Set
40012	FAIL	Cross Site Scripting (Reflected)
40014	FAIL	Cross Site Scripting (Persistent)
40018	FAIL	SQL Injection
90033	FAIL	Loosely Scoped Cookie
```

#### Verification Steps

- [ ] ZAP baseline scan runs weekly in CI/CD
- [ ] Custom rules file tailored to application
- [ ] FAIL rules for critical vulnerabilities (XSS, SQLi, CSRF)
- [ ] Reports archived for compliance
- [ ] Scan results reviewed within 48 hours

### 2. Nuclei Scanning

#### Nuclei Template Scanning

```bash
# PASS: CORRECT — Nuclei scan with targeted templates
# Install Nuclei
go install github.com/projectdiscovery/nuclei/v3/cmd/nuclei@latest

# Run with OWASP templates
nuclei -u https://staging.example.com \
  -t cves/ \
  -t vulnerabilities/ \
  -t misconfiguration/ \
  -t exposures/ \
  -severity critical,high \
  -o nuclei-results.json \
  -json

# Run with custom templates for your stack
nuclei -u https://staging.example.com \
  -t ./custom-templates/ \
  -severity critical,high,medium
```

#### Custom Nuclei Template

```yaml
# custom-templates/nextjs-debug-exposed.yaml
id: nextjs-debug-mode
info:
  name: Next.js Debug Mode Exposed
  severity: high
  description: Next.js debug/error page accessible in production

http:
  - method: GET
    path:
      - "{{BaseURL}}/_next/data"
      - "{{BaseURL}}/api/__nextjs_original-stack-frame"
    matchers:
      - type: status
        status:
          - 200
      - type: word
        words:
          - "sourceStackFrame"
          - "__nextjs"
        condition: or
```

#### Verification Steps

- [ ] Nuclei scans run against staging before production deploy
- [ ] Critical and high severity templates always included
- [ ] Custom templates for application-specific checks
- [ ] Results triaged and tracked in issue tracker
- [ ] False positives documented and filtered

### 3. API Security Testing

#### OWASP API Top 10 Tests

```typescript
// PASS: CORRECT — Automated API security test suite
import { describe, test, expect } from 'vitest';

describe('API Security Tests', () => {
  // API1: Broken Object Level Authorization
  test('cannot access other users resources', async () => {
    const userAToken = await getToken('user-a');
    const res = await fetch('/api/users/user-b/profile', {
      headers: { Authorization: `Bearer ${userAToken}` },
    });
    expect(res.status).toBe(403);
  });

  // API2: Broken Authentication
  test('rejects expired tokens', async () => {
    const expiredToken = createExpiredJWT();
    const res = await fetch('/api/protected', {
      headers: { Authorization: `Bearer ${expiredToken}` },
    });
    expect(res.status).toBe(401);
  });

  // API3: Broken Object Property Level Authorization
  test('cannot modify readonly fields', async () => {
    const res = await fetch('/api/users/me', {
      method: 'PATCH',
      headers: { Authorization: `Bearer ${userToken}` },
      body: JSON.stringify({ role: 'admin', verified: true }),
    });
    const user = await res.json();
    expect(user.role).not.toBe('admin');
  });

  // API4: Unrestricted Resource Consumption
  test('enforces rate limits', async () => {
    const requests = Array.from({ length: 101 }, () =>
      fetch('/api/search', { headers: { Authorization: `Bearer ${token}` } }),
    );
    const responses = await Promise.all(requests);
    const rateLimited = responses.filter((r) => r.status === 429);
    expect(rateLimited.length).toBeGreaterThan(0);
  });

  // API5: Broken Function Level Authorization
  test('non-admin cannot access admin endpoints', async () => {
    const userToken = await getToken('regular-user');
    const res = await fetch('/api/admin/users', {
      headers: { Authorization: `Bearer ${userToken}` },
    });
    expect(res.status).toBe(403);
  });
});
```

```python
# PASS: CORRECT — Python API security tests
import pytest
import httpx

class TestAPISecurity:
    """OWASP API Top 10 security tests."""

    async def test_bola_prevention(self, client: httpx.AsyncClient, user_a_token: str):
        """API1: Broken Object Level Authorization."""
        res = await client.get(
            "/api/users/user-b/profile",
            headers={"Authorization": f"Bearer {user_a_token}"},
        )
        assert res.status_code == 403

    async def test_mass_assignment_prevention(self, client: httpx.AsyncClient, user_token: str):
        """API3: Cannot modify protected fields."""
        res = await client.patch(
            "/api/users/me",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"role": "admin", "is_verified": True},
        )
        data = res.json()
        assert data.get("role") != "admin"

    async def test_rate_limiting(self, client: httpx.AsyncClient):
        """API4: Unrestricted Resource Consumption."""
        responses = []
        for _ in range(101):
            res = await client.get("/api/search")
            responses.append(res.status_code)
        assert 429 in responses
```

#### Verification Steps

- [ ] OWASP API Top 10 covered in test suite
- [ ] BOLA tests for every resource endpoint
- [ ] Mass assignment tests for all mutation endpoints
- [ ] Rate limiting verified for all public endpoints
- [ ] Authentication boundary tests (expired, invalid, missing tokens)

### 4. CI/CD Integration

#### DAST Pipeline Stage

```yaml
# PASS: CORRECT — DAST stage in deployment pipeline
# .github/workflows/deploy.yml
jobs:
  deploy-staging:
    runs-on: ubuntu-latest
    steps:
      - name: Deploy to staging
        run: ./deploy.sh staging

  dast-scan:
    needs: deploy-staging
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Run ZAP Full Scan
        uses: zaproxy/action-full-scan@v0.10.0
        with:
          target: 'https://staging.example.com'
          rules_file_name: '.zap/rules.tsv'

      - name: Run Nuclei
        run: |
          nuclei -u https://staging.example.com \
            -t cves/ -t vulnerabilities/ \
            -severity critical,high \
            -o nuclei-results.json -json

      - name: Fail on critical findings
        run: |
          if grep -q '"severity":"critical"' nuclei-results.json; then
            echo "Critical vulnerability found — blocking deployment"
            exit 1
          fi

  deploy-production:
    needs: dast-scan
    runs-on: ubuntu-latest
    steps:
      - name: Deploy to production
        run: ./deploy.sh production
```

#### Verification Steps

- [ ] DAST scan gates production deployments
- [ ] Critical findings block deployment automatically
- [ ] Scan runs against staging (not production)
- [ ] Results stored for audit trail
- [ ] Scan duration within acceptable CI/CD time budget

### 5. Penetration Testing Methodology

#### Pre-Engagement

```markdown
## Pen Test Scope Document
- **Target**: [application URL, API endpoints]
- **Type**: Black-box / Grey-box / White-box
- **Authorization**: [signed authorization document reference]
- **Rules of Engagement**:
  - No denial-of-service testing
  - No social engineering (unless agreed)
  - Testing hours: [specified window]
  - Emergency contact: [security team contact]
- **Out of Scope**: [third-party services, production databases]
```

#### Testing Phases

```markdown
1. **Reconnaissance**: Map attack surface (endpoints, parameters, auth flows)
2. **Vulnerability Scanning**: Automated ZAP + Nuclei scans
3. **Manual Testing**: Business logic flaws, auth bypass, privilege escalation
4. **Exploitation**: Confirm exploitability of findings (with care)
5. **Reporting**: Severity-rated findings with reproduction steps and remediation
6. **Retesting**: Verify fixes after remediation
```

#### Verification Steps

- [ ] Written authorization obtained before testing
- [ ] Scope clearly defined and agreed upon
- [ ] Testing performed on staging/test environment
- [ ] Findings documented with severity, impact, and remediation
- [ ] Retesting scheduled after remediation

## Pre-Deployment DAST Checklist

Before ANY production deployment:

- [ ] **ZAP Scan**: Baseline scan completed with no FAIL-level alerts
- [ ] **Nuclei Scan**: No critical/high severity findings
- [ ] **API Tests**: OWASP API Top 10 test suite passing
- [ ] **CI/CD Gate**: DAST stage integrated and enforced
- [ ] **Pen Test**: Conducted at least annually (or after major changes)
- [ ] **Findings Tracked**: All findings in issue tracker with owners
- [ ] **False Positives**: Documented and suppressed with justification

## Resources

- [OWASP ZAP](https://www.zaproxy.org/)
- [Nuclei by ProjectDiscovery](https://nuclei.projectdiscovery.io/)
- [OWASP API Security Top 10](https://owasp.org/API-Security/)
- [OWASP Testing Guide](https://owasp.org/www-project-web-security-testing-guide/)
- [PTES Technical Guidelines](http://www.pentest-standard.org/)

**Remember**: DAST finds vulnerabilities that static analysis cannot — runtime misconfigurations, broken auth flows, and business logic flaws. It must complement SAST, not replace it. Always test against staging environments with proper authorization.
