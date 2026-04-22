| name | description |
|------|-------------|
| iac-security-scanning | Use this skill when writing or reviewing Terraform, CloudFormation, Kubernetes manifests, or Dockerfiles. Provides IaC security scanning with tfsec, checkov, Snyk IaC, and Kubernetes policy enforcement. |

# Infrastructure as Code Security Scanning Skill

This skill ensures infrastructure-as-code definitions follow security best practices through automated scanning with tfsec, checkov, Snyk IaC, and Kubernetes policy engines.

## When to Activate

- Writing or reviewing Terraform configurations
- Creating or modifying Kubernetes manifests
- Writing Dockerfiles or docker-compose files
- Configuring CloudFormation templates
- Setting up CI/CD infrastructure pipelines
- Reviewing Helm charts for security issues

## IaC Security Checklist

### 1. Terraform Security with tfsec

#### tfsec CI/CD Integration

```yaml
# PASS: CORRECT — tfsec in GitHub Actions
name: IaC Security Scan
on:
  pull_request:
    paths:
      - 'terraform/**'
      - 'infra/**'

jobs:
  tfsec:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: tfsec scan
        uses: aquasecurity/tfsec-action@v1.0.3
        with:
          working_directory: terraform/
          soft_fail: false  # Fail the build on findings

      - name: Upload SARIF
        if: always()
        uses: github/codeql-action/upload-sarif@v3
        with:
          sarif_file: results.sarif
```

#### Common tfsec Findings

```terraform
# FAIL: WRONG — S3 bucket without encryption
resource "aws_s3_bucket" "data" {
  bucket = "my-data-bucket"
  # Missing encryption configuration
}

# PASS: CORRECT — S3 bucket with encryption and versioning
resource "aws_s3_bucket" "data" {
  bucket = "my-data-bucket"
}

resource "aws_s3_bucket_server_side_encryption_configuration" "data" {
  bucket = aws_s3_bucket.data.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.bucket_key.arn
    }
  }
}

resource "aws_s3_bucket_versioning" "data" {
  bucket = aws_s3_bucket.data.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_public_access_block" "data" {
  bucket = aws_s3_bucket.data.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
```

```terraform
# FAIL: WRONG — RDS without encryption, publicly accessible
resource "aws_db_instance" "main" {
  engine               = "postgres"
  instance_class       = "db.t3.micro"
  publicly_accessible  = true
  storage_encrypted    = false
}

# PASS: CORRECT — RDS hardened
resource "aws_db_instance" "main" {
  engine               = "postgres"
  instance_class       = "db.t3.micro"
  publicly_accessible  = false
  storage_encrypted    = true
  kms_key_id           = aws_kms_key.rds_key.arn
  deletion_protection  = true
  backup_retention_period = 30

  vpc_security_group_ids = [aws_security_group.db.id]
  db_subnet_group_name   = aws_db_subnet_group.private.name
}
```

#### Verification Steps

- [ ] tfsec runs on every PR touching infrastructure code
- [ ] No critical or high severity findings
- [ ] S3 buckets encrypted and private by default
- [ ] RDS instances not publicly accessible
- [ ] Security groups follow least privilege
- [ ] tfsec custom rules for organization-specific policies

### 2. Checkov Multi-Framework Scanning

#### Checkov Configuration

```yaml
# .checkov.yml — Checkov configuration
framework:
  - terraform
  - kubernetes
  - dockerfile
  - github_actions

skip-check:
  - CKV_AWS_18  # Skip if intentionally public (document why)

compact: true
output: sarif
```

```bash
# Run checkov locally
checkov -d terraform/ --framework terraform --output sarif
checkov -d k8s/ --framework kubernetes
checkov -f Dockerfile --framework dockerfile
```

#### Checkov Kubernetes Findings

```yaml
# FAIL: WRONG — Running as root, no resource limits
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api-server
spec:
  template:
    spec:
      containers:
        - name: api
          image: myapp:latest  # No tag pinning
          # No securityContext
          # No resource limits

# PASS: CORRECT — Hardened pod spec
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api-server
spec:
  template:
    spec:
      securityContext:
        runAsNonRoot: true
        seccompProfile:
          type: RuntimeDefault
      containers:
        - name: api
          image: myapp:v1.2.3@sha256:abc123...  # Pinned with digest
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities:
              drop: ["ALL"]
          resources:
            limits:
              cpu: "500m"
              memory: "256Mi"
            requests:
              cpu: "100m"
              memory: "128Mi"
          livenessProbe:
            httpGet:
              path: /health
              port: 8080
```

#### Verification Steps

- [ ] Checkov scans Terraform, Kubernetes, and Dockerfiles
- [ ] No containers running as root
- [ ] Resource limits set on all containers
- [ ] Images pinned with digest (not just tag)
- [ ] Read-only root filesystem where possible
- [ ] All capabilities dropped, only necessary ones added

### 3. Snyk IaC

#### Snyk IaC CI/CD

```yaml
# PASS: CORRECT — Snyk IaC in pipeline
- name: Snyk IaC Test
  uses: snyk/actions/iac@master
  env:
    SNYK_TOKEN: ${{ secrets.SNYK_TOKEN }}
  with:
    file: terraform/
    args: --severity-threshold=high

- name: Snyk IaC Monitor
  uses: snyk/actions/iac@master
  env:
    SNYK_TOKEN: ${{ secrets.SNYK_TOKEN }}
  with:
    command: monitor
    file: terraform/
```

#### Verification Steps

- [ ] Snyk IaC integrated in CI/CD pipeline
- [ ] High and critical findings block deployment
- [ ] Continuous monitoring enabled
- [ ] Findings tracked in Snyk dashboard

### 4. Kubernetes Security Policies

#### OPA Gatekeeper Constraints

```yaml
# PASS: CORRECT — Require non-root containers
apiVersion: constraints.gatekeeper.sh/v1beta1
kind: K8sRequireNonRoot
metadata:
  name: require-non-root
spec:
  match:
    kinds:
      - apiGroups: ["apps"]
        kinds: ["Deployment", "StatefulSet"]
    namespaces: ["production", "staging"]

---
# Require resource limits
apiVersion: constraints.gatekeeper.sh/v1beta1
kind: K8sRequireResourceLimits
metadata:
  name: require-resource-limits
spec:
  match:
    kinds:
      - apiGroups: ["apps"]
        kinds: ["Deployment"]
  parameters:
    maxCpu: "2"
    maxMemory: "2Gi"

---
# Block privileged containers
apiVersion: constraints.gatekeeper.sh/v1beta1
kind: K8sPSPPrivilegedContainer
metadata:
  name: block-privileged
spec:
  match:
    kinds:
      - apiGroups: [""]
        kinds: ["Pod"]
    namespaces: ["production"]
```

#### Kyverno Policies

```yaml
# PASS: CORRECT — Kyverno policy: disallow latest tag
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: disallow-latest-tag
spec:
  validationFailureAction: enforce
  rules:
    - name: validate-image-tag
      match:
        resources:
          kinds: ["Pod"]
      validate:
        message: "Images must use a specific tag, not 'latest'"
        pattern:
          spec:
            containers:
              - image: "!*:latest"
```

#### Verification Steps

- [ ] Policy engine (Gatekeeper or Kyverno) deployed
- [ ] Non-root container policy enforced
- [ ] Resource limits policy enforced
- [ ] Image tag pinning policy enforced
- [ ] Privileged container policy enforced
- [ ] Policies tested in staging before production

### 5. Dockerfile Security

```dockerfile
# FAIL: WRONG — Running as root, using latest, no multi-stage
FROM node:latest
COPY . .
RUN npm install
EXPOSE 3000
CMD ["node", "server.js"]

# PASS: CORRECT — Hardened Dockerfile
FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci --only=production
COPY . .
RUN npm run build

FROM node:20-alpine
RUN addgroup -S appgroup && adduser -S appuser -G appgroup
WORKDIR /app
COPY --from=builder /app/dist ./dist
COPY --from=builder /app/node_modules ./node_modules
USER appuser
EXPOSE 3000
HEALTHCHECK --interval=30s CMD wget -q --spider http://localhost:3000/health || exit 1
CMD ["node", "dist/server.js"]
```

#### Verification Steps

- [ ] Multi-stage builds used (minimize image size)
- [ ] Non-root USER specified
- [ ] Specific base image tag (not latest)
- [ ] Alpine or distroless base images preferred
- [ ] HEALTHCHECK defined
- [ ] No secrets in Dockerfile or build args

## Pre-Deployment IaC Security Checklist

Before ANY infrastructure deployment:

- [ ] **tfsec**: No high/critical findings in Terraform
- [ ] **Checkov**: All frameworks scanned (TF, K8s, Docker)
- [ ] **Snyk IaC**: Continuous monitoring enabled
- [ ] **K8s Policies**: Gatekeeper/Kyverno enforcing security policies
- [ ] **Dockerfiles**: Multi-stage, non-root, pinned tags
- [ ] **CI/CD Gate**: IaC scans block deployment on critical findings
- [ ] **Drift Detection**: Infrastructure drift monitored

## Resources

- [tfsec Documentation](https://aquasecurity.github.io/tfsec/)
- [Checkov Documentation](https://www.checkov.io/)
- [Snyk IaC Documentation](https://docs.snyk.io/scan-using-snyk/snyk-iac)
- [OPA Gatekeeper](https://open-policy-agent.github.io/gatekeeper/)
- [Kyverno Documentation](https://kyverno.io/docs/)

**Remember**: Infrastructure misconfigurations are the #1 cause of cloud security breaches. Scanning IaC before deployment catches issues before they reach production. Shift security left — fix it in the PR, not in the incident response.
