# Security Review Command

Run a comprehensive security review on the codebase using OWASP Top 10 checklist.

## Instructions

Perform a security audit in this order:

1. **Secrets Detection**
   - Search for hardcoded API keys, passwords, tokens in source files
   - Check `.env` files are not committed to git
   - Verify secrets use environment variables

2. **OWASP Top 10 Scan**
   - **Injection** — Check SQL queries are parameterized, user input sanitized
   - **Broken Auth** — Passwords hashed (bcrypt/argon2)? JWT validated? Sessions secure?
   - **Sensitive Data** — HTTPS enforced? PII encrypted? Logs sanitized?
   - **XXE** — XML parsers configured securely?
   - **Broken Access** — Auth checked on every route? CORS configured properly?
   - **Misconfiguration** — Debug mode off in prod? Security headers set?
   - **XSS** — Output escaped? CSP set?
   - **Insecure Deserialization** — User input deserialized safely?
   - **Known Vulnerabilities** — Dependencies up to date?
   - **Insufficient Logging** — Security events logged?

3. **Code Pattern Review**
   Flag these patterns immediately:
   - Hardcoded secrets → Use environment variables
   - Shell commands with user input → Use safe APIs
   - String-concatenated SQL → Parameterized queries
   - innerHTML with user input → Use textContent or sanitizer
   - No auth check on route → Add authentication middleware
   - Plaintext password comparison → Use bcrypt.compare()
   - No rate limiting → Add rate limiter

4. **Dependency Audit**
   - Python: `pip audit` or `safety check`
   - Node.js: `npm audit --audit-level=high`

5. **DAST Scan** (if `dast` or `full` argument)
   - Run OWASP ZAP baseline scan against local/staging URL
   - Run Nuclei with critical/high severity templates
   - Check for exposed debug endpoints, missing security headers
   - Verify rate limiting and auth boundaries with API tests

## Output

Produce a security report:

```
SECURITY REVIEW: [PASS/FAIL]

Secrets:        [OK/X found]
Injection:      [OK/X risks]
Auth:           [OK/X issues]
XSS:            [OK/X risks]
Dependencies:   [OK/X vulnerabilities]

Critical Issues: [count]
High Issues:     [count]
Medium Issues:   [count]

Ready for production: [YES/NO]
```

List all findings with severity, location, and fix suggestion.

## Arguments

$ARGUMENTS can be:
- `quick` - Secrets + injection only
- `full` - Complete OWASP scan (default)
- `deps` - Dependency audit only
- `dast` - DAST scan (ZAP + Nuclei against running app)
- `compliance` - GDPR + PCI DSS + encryption + MFA compliance audit
