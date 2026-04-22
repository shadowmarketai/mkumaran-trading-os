# Security Guidelines

## Mandatory Security Checks

Before ANY commit:
- [ ] No hardcoded secrets (API keys, passwords, tokens)
- [ ] All user inputs validated
- [ ] SQL injection prevention (parameterized queries)
- [ ] XSS prevention (sanitized HTML)
- [ ] CSRF protection enabled
- [ ] Authentication/authorization verified
- [ ] Rate limiting on all endpoints
- [ ] Error messages don't leak sensitive data

## Secret Management

- NEVER hardcode secrets in source code
- ALWAYS use environment variables or a secret manager
- Validate that required secrets are present at startup
- Rotate any secrets that may have been exposed

## Data Privacy (GDPR)

- Collect only data that is strictly necessary (data minimization)
- Document lawful basis for each data processing activity
- Implement right-to-erasure (deletion) and right-to-portability (export)
- Store consent records with timestamp, IP, and policy version
- Set retention policies and enforce them automatically
- Notify supervisory authority within 72 hours of qualifying breaches

## SSRF Prevention

- NEVER fetch arbitrary user-provided URLs without validation
- Maintain an allowlist of permitted external hosts
- Block private/internal IP ranges (127.x, 10.x, 172.16-31.x, 192.168.x)
- Block cloud metadata endpoints (169.254.169.254)
- Require HTTPS for all outbound requests
- Resolve DNS and verify IP before making the request

## Security Response Protocol

If security issue found:
1. STOP immediately
2. Use **security-reviewer** agent
3. Fix CRITICAL issues before continuing
4. Rotate any exposed secrets
5. Review entire codebase for similar issues
