"""
HMAC verification for inbound webhooks.

The TradingView webhook (`/api/tv_webhook`) accepts unauthenticated POSTs
because Pine Script can't carry rich auth headers. To raise the bar
without breaking the Pine alert flow, callers may sign the raw request
body with a shared secret (HMAC-SHA256, hex-encoded) and attach it as
`X-Webhook-Signature`. The verifier here uses constant-time comparison
to avoid timing oracles.

Usage in a route:

    from mcp_server.webhook_auth import verify_tv_webhook_signature
    body = await request.body()
    sig = request.headers.get("X-Webhook-Signature", "")
    err = verify_tv_webhook_signature(body, sig)
    if err:
        raise HTTPException(401, err)

When `settings.TV_WEBHOOK_SECRET` is empty, the verifier is permissive
(returns None) but logs a one-line warning so the operator notices.
That's the migration path — flip the secret on once Pine alerts carry
the matching signature.
"""

from __future__ import annotations

import hashlib
import hmac
import logging

from mcp_server.config import settings

logger = logging.getLogger(__name__)


def compute_hmac(body: bytes, secret: str) -> str:
    """Return hex-encoded HMAC-SHA256 of `body` keyed by `secret`."""
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def verify_tv_webhook_signature(
    body: bytes, signature: str | None,
) -> str | None:
    """Validate `signature` against HMAC-SHA256(body, TV_WEBHOOK_SECRET).

    Returns None on success (or when no secret is configured), or a
    short error message suitable for the 401 detail. The caller is
    responsible for raising the HTTP error.
    """
    secret = settings.TV_WEBHOOK_SECRET
    if not secret:
        # Soft-fail — secret not configured. Log so operators can see the
        # exposure in their structured logs.
        logger.warning(
            "TV webhook accepted without HMAC: TV_WEBHOOK_SECRET is unset. "
            "Set it in env to enforce signature verification."
        )
        return None

    if not signature:
        return "Missing X-Webhook-Signature header"

    expected = compute_hmac(body, secret)
    # Constant-time compare. hmac.compare_digest also handles unequal lengths.
    if not hmac.compare_digest(expected, signature.strip().lower()):
        return "Invalid webhook signature"
    return None
