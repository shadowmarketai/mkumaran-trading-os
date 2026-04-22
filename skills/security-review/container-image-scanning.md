| name | description |
|------|-------------|
| container-image-scanning | Use this skill when building Docker images, managing container registries, generating SBOMs, or implementing image signing. Covers Trivy, Grype, Syft, cosign, and base image hardening. |

# Container Image Scanning Skill

This skill ensures container images are free of known vulnerabilities, properly signed, and built on hardened base images with complete software bills of materials (SBOMs).

## When to Activate

- Building or modifying Docker images
- Pushing images to container registries
- Setting up container scanning in CI/CD
- Generating SBOMs for compliance
- Implementing image signing and verification
- Selecting or hardening base images
- Responding to CVE disclosures affecting container images

## Container Security Checklist

### 1. Trivy — Vulnerability Scanning

#### Trivy CI/CD Integration

```yaml
# PASS: CORRECT — Trivy scan in GitHub Actions
name: Container Security
on:
  push:
    branches: [main]
  pull_request:

jobs:
  trivy-scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Build image
        run: docker build -t myapp:${{ github.sha }} .

      - name: Trivy vulnerability scan
        uses: aquasecurity/trivy-action@0.28.0
        with:
          image-ref: 'myapp:${{ github.sha }}'
          format: 'sarif'
          output: 'trivy-results.sarif'
          severity: 'CRITICAL,HIGH'
          exit-code: '1'  # Fail on critical/high

      - name: Upload Trivy scan results
        uses: github/codeql-action/upload-sarif@v3
        if: always()
        with:
          sarif_file: 'trivy-results.sarif'

      - name: Trivy SBOM generation
        uses: aquasecurity/trivy-action@0.28.0
        with:
          image-ref: 'myapp:${{ github.sha }}'
          format: 'cyclonedx'
          output: 'sbom.json'
```

#### Trivy Local Scanning

```bash
# Scan a Docker image
trivy image myapp:latest --severity CRITICAL,HIGH

# Scan filesystem (before building)
trivy fs . --severity CRITICAL,HIGH

# Scan with JSON output for CI parsing
trivy image myapp:latest --format json --output trivy-report.json

# Scan running containers
trivy image --input myapp.tar

# Generate SBOM
trivy image myapp:latest --format cyclonedx --output sbom.json
```

#### Verification Steps

- [ ] Trivy scans every image before push to registry
- [ ] Critical and high vulnerabilities block deployment
- [ ] SARIF reports uploaded for GitHub Security tab integration
- [ ] Scan results stored for audit trail
- [ ] Base image vulnerabilities tracked separately

### 2. Grype — Vulnerability Scanning

#### Grype CI/CD Integration

```yaml
# PASS: CORRECT — Grype as alternative/complementary scanner
- name: Grype scan
  uses: anchore/scan-action@v4
  with:
    image: 'myapp:${{ github.sha }}'
    fail-build: true
    severity-cutoff: high
    output-format: sarif

- name: Upload Grype results
  uses: github/codeql-action/upload-sarif@v3
  if: always()
  with:
    sarif_file: results.sarif
```

```bash
# Local Grype scanning
grype myapp:latest --fail-on high
grype sbom:sbom.json  # Scan from SBOM
grype dir:. --scope all-layers  # Scan all image layers
```

#### Verification Steps

- [ ] Grype scans complement Trivy (different vulnerability DBs)
- [ ] SBOM-based scanning enabled
- [ ] All image layers scanned (not just final layer)
- [ ] Results compared across scanners for completeness

### 3. Syft — SBOM Generation

#### Comprehensive SBOM

```bash
# Generate CycloneDX SBOM
syft myapp:latest -o cyclonedx-json > sbom-cyclonedx.json

# Generate SPDX SBOM
syft myapp:latest -o spdx-json > sbom-spdx.json

# Generate from Dockerfile context
syft dir:. -o cyclonedx-json > sbom-source.json
```

#### SBOM in CI/CD

```yaml
# PASS: CORRECT — SBOM generation and attestation
- name: Generate SBOM
  run: |
    syft myapp:${{ github.sha }} -o cyclonedx-json > sbom.json

- name: Attest SBOM
  run: |
    cosign attest \
      --predicate sbom.json \
      --type cyclonedx \
      --key cosign.key \
      myregistry.com/myapp:${{ github.sha }}

- name: Upload SBOM artifact
  uses: actions/upload-artifact@v4
  with:
    name: sbom
    path: sbom.json
```

#### Verification Steps

- [ ] SBOM generated for every production image
- [ ] CycloneDX or SPDX format used
- [ ] SBOM includes all dependencies (OS + app)
- [ ] SBOM attached as image attestation
- [ ] SBOM stored for compliance auditing

### 4. Image Signing with Cosign

#### Cosign Signing and Verification

```bash
# Generate signing keypair
cosign generate-key-pair

# Sign an image
cosign sign --key cosign.key myregistry.com/myapp:v1.2.3

# Verify an image signature
cosign verify --key cosign.pub myregistry.com/myapp:v1.2.3

# Keyless signing with GitHub OIDC (recommended for CI)
cosign sign --yes myregistry.com/myapp:v1.2.3
```

#### CI/CD Signing Pipeline

```yaml
# PASS: CORRECT — Build, scan, sign pipeline
jobs:
  build-scan-sign:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write
      id-token: write  # For keyless signing

    steps:
      - uses: actions/checkout@v4

      - name: Build and push image
        run: |
          docker build -t ghcr.io/${{ github.repository }}:${{ github.sha }} .
          docker push ghcr.io/${{ github.repository }}:${{ github.sha }}

      - name: Scan with Trivy
        uses: aquasecurity/trivy-action@0.28.0
        with:
          image-ref: 'ghcr.io/${{ github.repository }}:${{ github.sha }}'
          exit-code: '1'
          severity: 'CRITICAL,HIGH'

      - name: Install cosign
        uses: sigstore/cosign-installer@v3

      - name: Sign image (keyless)
        run: |
          cosign sign --yes ghcr.io/${{ github.repository }}:${{ github.sha }}

      - name: Verify signature
        run: |
          cosign verify \
            --certificate-oidc-issuer https://token.actions.githubusercontent.com \
            --certificate-identity-regexp 'github.com/${{ github.repository }}' \
            ghcr.io/${{ github.repository }}:${{ github.sha }}
```

#### Kubernetes Admission — Verify Signatures

```yaml
# PASS: CORRECT — Kyverno policy to verify image signatures
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: verify-image-signatures
spec:
  validationFailureAction: enforce
  rules:
    - name: verify-cosign-signature
      match:
        resources:
          kinds: ["Pod"]
      verifyImages:
        - imageReferences: ["ghcr.io/myorg/*"]
          attestors:
            - entries:
                - keyless:
                    issuer: "https://token.actions.githubusercontent.com"
                    subject: "https://github.com/myorg/*"
```

#### Verification Steps

- [ ] All production images signed before deployment
- [ ] Keyless signing with OIDC in CI/CD (preferred)
- [ ] Kubernetes admission policy verifies signatures
- [ ] Unsigned images rejected at deployment
- [ ] Signing keys/certificates rotated regularly

### 5. Base Image Hardening

#### Choosing Secure Base Images

```dockerfile
# PREFERRED: Distroless (minimal attack surface)
FROM gcr.io/distroless/nodejs20-debian12
COPY --from=builder /app/dist /app
CMD ["app/server.js"]

# GOOD: Alpine (small, fewer packages)
FROM node:20-alpine
RUN apk --no-cache add tini
USER node
ENTRYPOINT ["/sbin/tini", "--"]
CMD ["node", "server.js"]

# AVOID: Full Debian/Ubuntu (large attack surface)
FROM node:20  # ~900MB, hundreds of packages
```

#### Base Image Update Policy

```yaml
# PASS: CORRECT — Renovate/Dependabot for base image updates
# renovate.json
{
  "extends": ["config:recommended"],
  "docker": {
    "enabled": true
  },
  "packageRules": [
    {
      "matchDatasources": ["docker"],
      "matchUpdateTypes": ["patch", "minor"],
      "automerge": true
    },
    {
      "matchDatasources": ["docker"],
      "matchUpdateTypes": ["major"],
      "automerge": false,
      "labels": ["security-review"]
    }
  ]
}
```

#### Verification Steps

- [ ] Distroless or Alpine base images used
- [ ] Base image version pinned (not `latest`)
- [ ] Automated base image update PRs (Renovate/Dependabot)
- [ ] Base images scanned for vulnerabilities
- [ ] Custom base images rebuilt regularly

### 6. Registry Security

```bash
# PASS: CORRECT — Registry with vulnerability scanning
# Enable scanning in AWS ECR
aws ecr put-image-scanning-configuration \
  --repository-name myapp \
  --image-scanning-configuration scanOnPush=true

# Enable immutable tags (prevent tag overwriting)
aws ecr put-image-tag-mutability \
  --repository-name myapp \
  --image-tag-mutability IMMUTABLE

# Set lifecycle policy (clean up old images)
aws ecr put-lifecycle-policy \
  --repository-name myapp \
  --lifecycle-policy-text '{
    "rules": [{
      "rulePriority": 1,
      "description": "Keep last 10 images",
      "selection": {
        "tagStatus": "any",
        "countType": "imageCountMoreThan",
        "countNumber": 10
      },
      "action": { "type": "expire" }
    }]
  }'
```

#### Verification Steps

- [ ] Registry scan-on-push enabled
- [ ] Immutable tags configured
- [ ] Lifecycle policies clean old images
- [ ] Registry access controlled (IAM/RBAC)
- [ ] Registry accessible only from trusted networks

## Pre-Deployment Container Security Checklist

Before ANY production container deployment:

- [ ] **Trivy/Grype**: No critical/high vulnerabilities in image
- [ ] **SBOM**: Generated and stored for every production image
- [ ] **Signed**: Image signed with cosign (keyless or key-based)
- [ ] **Base Image**: Distroless or Alpine, pinned version
- [ ] **Non-Root**: Container runs as non-root user
- [ ] **Read-Only**: Root filesystem is read-only
- [ ] **No Secrets**: No secrets baked into image layers
- [ ] **Registry**: Scan-on-push and immutable tags enabled
- [ ] **Admission**: Kubernetes verifies image signatures
- [ ] **Updates**: Automated base image update pipeline

## Resources

- [Trivy Documentation](https://aquasecurity.github.io/trivy/)
- [Grype Documentation](https://github.com/anchore/grype)
- [Syft Documentation](https://github.com/anchore/syft)
- [Cosign Documentation](https://docs.sigstore.dev/cosign/overview/)
- [Google Distroless Images](https://github.com/GoogleContainerTools/distroless)
- [CIS Docker Benchmark](https://www.cisecurity.org/benchmark/docker)

**Remember**: A container image is only as secure as its weakest layer. Scanning catches known vulnerabilities, but hardening the base image, running as non-root, and signing images creates defense in depth. Unsigned images in production are like unsigned checks — anyone could have written them.
