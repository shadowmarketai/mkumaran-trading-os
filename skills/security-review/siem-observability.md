| name | description |
|------|-------------|
| siem-observability | Use this skill when setting up security monitoring, configuring log aggregation (ELK, Loki, Datadog), building alerting rules, creating security dashboards, or implementing log correlation for incident detection. |

# SIEM & Observability Skill

This skill ensures comprehensive security monitoring, log aggregation, alerting, and incident detection across all application layers.

## When to Activate

- Setting up centralized logging (ELK Stack, Grafana Loki, Datadog)
- Configuring security alerting rules
- Building security dashboards and visualizations
- Implementing log correlation for threat detection
- Setting up audit trails for compliance
- Configuring anomaly detection for suspicious activity
- Implementing structured logging for security events

## SIEM Checklist

### 1. Structured Security Logging

#### Security Event Schema

```typescript
// PASS: CORRECT — Structured security event logging
interface SecurityEvent {
  timestamp: string;       // ISO 8601
  level: 'info' | 'warn' | 'error' | 'critical';
  category: 'auth' | 'access' | 'data' | 'network' | 'admin';
  action: string;          // e.g., 'login_success', 'permission_denied'
  userId?: string;
  ip: string;
  userAgent?: string;
  resource?: string;
  result: 'success' | 'failure' | 'blocked';
  metadata?: Record<string, unknown>;
  correlationId: string;   // Request trace ID
}

function logSecurityEvent(event: SecurityEvent): void {
  // Structured JSON logging for SIEM ingestion
  const entry = {
    ...event,
    timestamp: event.timestamp || new Date().toISOString(),
    service: process.env.SERVICE_NAME,
    environment: process.env.NODE_ENV,
  };

  // Write to stdout for log aggregator pickup
  process.stdout.write(JSON.stringify(entry) + '\n');
}

// Usage examples
logSecurityEvent({
  timestamp: new Date().toISOString(),
  level: 'warn',
  category: 'auth',
  action: 'login_failed',
  ip: req.ip,
  userAgent: req.headers['user-agent'],
  result: 'failure',
  metadata: { reason: 'invalid_password', attempts: 3 },
  correlationId: req.headers['x-correlation-id'],
});

// FAIL: WRONG — Unstructured, inconsistent logging
console.log(`Login failed for ${email} from ${ip}`); // Not parseable by SIEM
```

```python
# PASS: CORRECT — Python structured security logging
import structlog
import json

logger = structlog.get_logger()

def log_security_event(
    category: str,
    action: str,
    result: str,
    ip: str,
    user_id: str | None = None,
    metadata: dict | None = None,
    correlation_id: str | None = None,
):
    logger.info(
        "security_event",
        category=category,
        action=action,
        result=result,
        ip=ip,
        user_id=user_id,
        metadata=metadata or {},
        correlation_id=correlation_id,
        service=os.environ.get("SERVICE_NAME"),
        environment=os.environ.get("ENVIRONMENT"),
    )

# Usage
log_security_event(
    category="auth",
    action="login_failed",
    result="failure",
    ip=request.client.host,
    metadata={"reason": "invalid_password", "attempts": 3},
)
```

#### Verification Steps

- [ ] All security events use structured JSON format
- [ ] Events include timestamp, category, action, result, IP, correlation ID
- [ ] No PII in log messages (hash user IDs if needed)
- [ ] Logs written to stdout/stderr for aggregator pickup
- [ ] Consistent schema across all services

### 2. Log Aggregation — ELK Stack

#### Filebeat Configuration

```yaml
# PASS: CORRECT — Filebeat shipping to Elasticsearch
# filebeat.yml
filebeat.inputs:
  - type: container
    paths:
      - '/var/lib/docker/containers/*/*.log'
    json.keys_under_root: true
    json.add_error_key: true

processors:
  - add_host_metadata: ~
  - add_cloud_metadata: ~
  - add_docker_metadata: ~

output.elasticsearch:
  hosts: ['${ELASTICSEARCH_HOSTS}']
  username: '${ELASTICSEARCH_USER}'
  password: '${ELASTICSEARCH_PASSWORD}'
  ssl.certificate_authorities: ['/etc/pki/ca.crt']
  indices:
    - index: "security-events-%{+yyyy.MM.dd}"
      when.contains:
        category: "auth"
    - index: "app-logs-%{+yyyy.MM.dd}"
```

#### Elasticsearch Index Template

```json
{
  "index_patterns": ["security-events-*"],
  "template": {
    "settings": {
      "number_of_replicas": 1,
      "index.lifecycle.name": "security-logs-policy",
      "index.lifecycle.rollover_alias": "security-events"
    },
    "mappings": {
      "properties": {
        "timestamp": { "type": "date" },
        "level": { "type": "keyword" },
        "category": { "type": "keyword" },
        "action": { "type": "keyword" },
        "userId": { "type": "keyword" },
        "ip": { "type": "ip" },
        "result": { "type": "keyword" },
        "correlationId": { "type": "keyword" }
      }
    }
  }
}
```

#### Verification Steps

- [ ] Logs shipped from all services to central store
- [ ] Index templates define proper field mappings
- [ ] Retention policies configured (90+ days for security logs)
- [ ] Log integrity protected (immutable storage or signing)
- [ ] Cross-service correlation via correlation ID

### 3. Log Aggregation — Grafana Loki

#### Loki with Promtail

```yaml
# PASS: CORRECT — Promtail scraping Docker logs
# promtail-config.yml
server:
  http_listen_port: 9080

positions:
  filename: /tmp/positions.yaml

clients:
  - url: http://loki:3100/loki/api/v1/push

scrape_configs:
  - job_name: containers
    static_configs:
      - targets: [localhost]
        labels:
          job: containerlogs
          __path__: /var/lib/docker/containers/*/*.log
    pipeline_stages:
      - json:
          expressions:
            level: level
            category: category
            action: action
      - labels:
          level:
          category:
          action:
```

#### LogQL Security Queries

```logql
# Failed logins in last hour
{category="auth", action="login_failed"} | json | count_over_time({category="auth", action="login_failed"}[1h])

# Brute force detection (>5 failures from same IP in 10 min)
sum by (ip) (count_over_time({category="auth", result="failure"} [10m])) > 5

# Privilege escalation attempts
{category="access", action=~"role_change|permission_grant"} | json | result="failure"

# Data exfiltration indicators (large exports)
{category="data", action="export"} | json | bytes > 10000000
```

#### Verification Steps

- [ ] Loki receives logs from all services
- [ ] Labels applied for efficient querying
- [ ] Security-specific LogQL queries documented
- [ ] Retention configured per log category
- [ ] Grafana datasource configured

### 4. Alerting Rules

#### Prometheus Alerting Rules

```yaml
# PASS: CORRECT — Security alerting rules
# alerting-rules.yml
groups:
  - name: security-alerts
    rules:
      - alert: BruteForceDetected
        expr: |
          sum by (ip) (
            rate(auth_login_failures_total[5m])
          ) > 10
        for: 2m
        labels:
          severity: critical
          category: security
        annotations:
          summary: "Brute force attack detected from {{ $labels.ip }}"
          description: "More than 10 failed logins per 5 minutes from IP {{ $labels.ip }}"

      - alert: UnusualAdminActivity
        expr: |
          count by (userId) (
            rate(admin_actions_total[1h])
          ) > 50
        for: 5m
        labels:
          severity: high
          category: security
        annotations:
          summary: "Unusual admin activity by {{ $labels.userId }}"

      - alert: HighErrorRate
        expr: |
          rate(http_requests_total{status=~"5.."}[5m])
          / rate(http_requests_total[5m]) > 0.05
        for: 5m
        labels:
          severity: high
        annotations:
          summary: "Error rate above 5% — possible attack or outage"

      - alert: SuspiciousDataExport
        expr: |
          sum by (userId) (
            data_export_bytes_total
          ) > 100000000
        for: 1m
        labels:
          severity: critical
          category: security
        annotations:
          summary: "Large data export by {{ $labels.userId }} (>100MB)"
```

#### Datadog Monitor Configuration

```python
# PASS: CORRECT — Datadog security monitor
from datadog_api_client.v1 import ApiClient, Configuration
from datadog_api_client.v1.api.monitors_api import MonitorsApi

config = Configuration()
with ApiClient(config) as api_client:
    api = MonitorsApi(api_client)

    # Brute force detection
    api.create_monitor(body={
        "name": "Brute Force Detection",
        "type": "log alert",
        "query": 'logs("category:auth action:login_failed").index("*").rollup("count").by("ip").last("5m") > 10',
        "message": "Brute force attack detected from {{ip.name}}. @security-team",
        "tags": ["security", "auth"],
        "options": {
            "thresholds": {"critical": 10, "warning": 5},
            "notify_no_data": False,
        },
    })
```

#### Verification Steps

- [ ] Brute force detection alert configured
- [ ] Privilege escalation alert configured
- [ ] Anomalous data access alert configured
- [ ] High error rate alert configured
- [ ] Alert routing to security team (Slack, PagerDuty, email)
- [ ] Alert fatigue minimized (tuned thresholds, no noise)

### 5. Security Dashboards

#### Grafana Dashboard Panels

```json
{
  "title": "Security Overview",
  "panels": [
    {
      "title": "Failed Logins (Last 24h)",
      "type": "stat",
      "targets": [{ "expr": "sum(increase(auth_login_failures_total[24h]))" }]
    },
    {
      "title": "Failed Logins by IP (Top 10)",
      "type": "table",
      "targets": [{ "expr": "topk(10, sum by (ip) (increase(auth_login_failures_total[24h])))" }]
    },
    {
      "title": "Auth Events Timeline",
      "type": "timeseries",
      "targets": [
        { "expr": "rate(auth_login_success_total[5m])", "legendFormat": "Success" },
        { "expr": "rate(auth_login_failures_total[5m])", "legendFormat": "Failure" }
      ]
    },
    {
      "title": "Active Security Alerts",
      "type": "alertlist"
    },
    {
      "title": "API Error Rate by Endpoint",
      "type": "heatmap",
      "targets": [{ "expr": "rate(http_requests_total{status=~'4..|5..'}[5m])" }]
    }
  ]
}
```

#### Verification Steps

- [ ] Security overview dashboard with key metrics
- [ ] Authentication events dashboard (successes, failures, by IP/user)
- [ ] API security dashboard (error rates, rate limit hits, suspicious requests)
- [ ] Admin activity dashboard
- [ ] Dashboard accessible to security team only

### 6. Log Correlation & Threat Detection

#### Correlation Rules

```typescript
// PASS: CORRECT — Multi-signal correlation engine
interface ThreatSignal {
  type: string;
  timestamp: Date;
  userId?: string;
  ip: string;
  severity: number;
}

async function correlateThreats(signals: ThreatSignal[]): Promise<ThreatAssessment> {
  const byIp = groupBy(signals, 'ip');

  for (const [ip, ipSignals] of Object.entries(byIp)) {
    const timeWindow = ipSignals.filter(
      (s) => Date.now() - s.timestamp.getTime() < 15 * 60 * 1000, // 15 min
    );

    // Correlation: multiple failed logins + admin endpoint access = attack
    const failedLogins = timeWindow.filter((s) => s.type === 'login_failed');
    const adminAccess = timeWindow.filter((s) => s.type === 'admin_access_denied');

    if (failedLogins.length > 5 && adminAccess.length > 0) {
      await triggerAlert({
        type: 'ACCOUNT_TAKEOVER_ATTEMPT',
        severity: 'critical',
        ip,
        evidence: { failedLogins: failedLogins.length, adminAttempts: adminAccess.length },
      });
    }
  }
}
```

#### Verification Steps

- [ ] Multi-signal correlation rules defined
- [ ] Correlation across authentication, access, and data events
- [ ] Time-window based pattern detection
- [ ] Automated alert generation on correlated threats
- [ ] False positive tracking and threshold tuning

## Pre-Deployment SIEM Checklist

Before ANY production deployment:

- [ ] **Structured Logging**: All services emit structured JSON security events
- [ ] **Aggregation**: Logs shipped to central SIEM (ELK/Loki/Datadog)
- [ ] **Retention**: Security logs retained 90+ days
- [ ] **Alerting**: Critical security alerts configured and tested
- [ ] **Dashboards**: Security overview dashboard operational
- [ ] **Correlation**: Multi-signal threat detection rules active
- [ ] **On-Call**: Security alert routing to on-call team configured
- [ ] **Compliance**: Audit trail meets regulatory requirements
- [ ] **Integrity**: Log tampering prevention in place

## Resources

- [ELK Stack Documentation](https://www.elastic.co/guide/en/elastic-stack/current/index.html)
- [Grafana Loki Documentation](https://grafana.com/docs/loki/latest/)
- [Datadog Security Monitoring](https://docs.datadoghq.com/security/)
- [MITRE ATT&CK Framework](https://attack.mitre.org/)
- [NIST Cybersecurity Framework](https://www.nist.gov/cyberframework)

**Remember**: You cannot protect what you cannot see. Comprehensive logging and monitoring is the foundation of security — without it, breaches go undetected for months. Average breach detection time without SIEM: 197 days. With SIEM: under 30 days.
