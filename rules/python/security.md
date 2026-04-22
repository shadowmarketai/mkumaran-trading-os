---
paths:
  - "**/*.py"
  - "**/*.pyi"
---
# Python Security

> This file extends [common/security.md](../common/security.md) with Python specific content.

## Secret Management

```python
import os
from dotenv import load_dotenv

load_dotenv()

api_key = os.environ["OPENAI_API_KEY"]  # Raises KeyError if missing
```

## Security Scanning

- Use **bandit** for static security analysis:
  ```bash
  bandit -r src/
  ```

## SSRF Prevention

```python
import ipaddress, socket
from urllib.parse import urlparse

ALLOWED_HOSTS = {"api.stripe.com", "api.github.com"}

def safe_request(url: str):
    parsed = urlparse(url)
    if parsed.hostname not in ALLOWED_HOSTS:
        raise ValueError("Host not in allowlist")
    ip = socket.gethostbyname(parsed.hostname)
    if ipaddress.ip_address(ip).is_private:
        raise ValueError("Private IP blocked")
    return httpx.get(url)
```

## Field-Level Encryption (Fernet)

```python
from cryptography.fernet import Fernet

key = Fernet.generate_key()  # Store in KMS / env var
f = Fernet(key)

encrypted = f.encrypt(b"sensitive-data")
decrypted = f.decrypt(encrypted)
```

## DAST Integration

```bash
# Run OWASP ZAP baseline scan against staging
docker run -t zaproxy/zap-stable zap-baseline.py -t https://staging.example.com

# Run Nuclei with critical/high templates
nuclei -u https://staging.example.com -severity critical,high
```

## Reference

See skill: `django-security` for Django-specific security guidelines (if applicable).
