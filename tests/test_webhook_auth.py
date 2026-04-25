"""Tests for mcp_server.webhook_auth — TV webhook HMAC verification."""

import hashlib
import hmac

import pytest

from mcp_server import webhook_auth
from mcp_server.config import settings


@pytest.fixture
def with_secret(monkeypatch):
    """Configure a known secret on the singleton settings; restore after."""
    monkeypatch.setattr(settings, "TV_WEBHOOK_SECRET", "test-secret-32bytes-XXXXXXXXXXXX")
    return settings.TV_WEBHOOK_SECRET


@pytest.fixture
def no_secret(monkeypatch):
    monkeypatch.setattr(settings, "TV_WEBHOOK_SECRET", "")


def _sign(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


# ── compute_hmac ────────────────────────────────────────────


def test_compute_hmac_is_deterministic():
    body = b'{"ticker":"RELIANCE"}'
    a = webhook_auth.compute_hmac(body, "secret")
    b = webhook_auth.compute_hmac(body, "secret")
    assert a == b


def test_compute_hmac_changes_with_body():
    a = webhook_auth.compute_hmac(b"body1", "secret")
    b = webhook_auth.compute_hmac(b"body2", "secret")
    assert a != b


def test_compute_hmac_changes_with_secret():
    a = webhook_auth.compute_hmac(b"body", "secret1")
    b = webhook_auth.compute_hmac(b"body", "secret2")
    assert a != b


# ── verify_tv_webhook_signature: valid path ─────────────────


def test_valid_signature_returns_none(with_secret):
    body = b'{"ticker":"RELIANCE","direction":"LONG"}'
    sig = _sign(body, with_secret)
    assert webhook_auth.verify_tv_webhook_signature(body, sig) is None


def test_signature_is_case_insensitive(with_secret):
    body = b'{"ticker":"RELIANCE"}'
    sig = _sign(body, with_secret).upper()
    # We lower-case the incoming signature before comparing — Pine alerts
    # may send either case depending on how the alert was templated.
    assert webhook_auth.verify_tv_webhook_signature(body, sig) is None


def test_signature_with_whitespace_stripped(with_secret):
    body = b'{"ticker":"RELIANCE"}'
    sig = "  " + _sign(body, with_secret) + "\n"
    assert webhook_auth.verify_tv_webhook_signature(body, sig) is None


# ── verify: rejection paths ────────────────────────────────


def test_missing_signature_rejected(with_secret):
    err = webhook_auth.verify_tv_webhook_signature(b"body", None)
    assert err == "Missing X-Webhook-Signature header"


def test_empty_signature_rejected(with_secret):
    err = webhook_auth.verify_tv_webhook_signature(b"body", "")
    assert err == "Missing X-Webhook-Signature header"


def test_wrong_signature_rejected(with_secret):
    body = b'{"ticker":"RELIANCE"}'
    err = webhook_auth.verify_tv_webhook_signature(body, "0" * 64)
    assert err == "Invalid webhook signature"


def test_signature_for_different_body_rejected(with_secret):
    body = b'{"ticker":"RELIANCE","entry":1000}'
    sig_for_other = _sign(b'{"ticker":"OTHER"}', with_secret)
    err = webhook_auth.verify_tv_webhook_signature(body, sig_for_other)
    assert err == "Invalid webhook signature"


def test_signature_with_wrong_secret_rejected(with_secret):
    body = b'{"ticker":"RELIANCE"}'
    sig = _sign(body, "wrong-secret")
    err = webhook_auth.verify_tv_webhook_signature(body, sig)
    assert err == "Invalid webhook signature"


# ── verify: permissive when secret unset ───────────────────


def test_permissive_when_secret_empty_passes(no_secret, caplog):
    """No secret configured → accept anything but log a warning."""
    with caplog.at_level("WARNING"):
        err = webhook_auth.verify_tv_webhook_signature(b"body", None)
    assert err is None
    assert any("TV_WEBHOOK_SECRET is unset" in m for m in caplog.messages)


def test_permissive_when_secret_empty_with_random_sig(no_secret, caplog):
    with caplog.at_level("WARNING"):
        err = webhook_auth.verify_tv_webhook_signature(b"body", "anyvalue")
    assert err is None


# ── Constant-time semantics ────────────────────────────────


def test_uses_constant_time_compare(monkeypatch, with_secret):
    """Sanity: verify the call routes through hmac.compare_digest.

    If a future refactor swaps in `==`, this test fires. Catches a real
    timing-attack regression.
    """
    calls: list[tuple] = []
    real = hmac.compare_digest

    def spy(a, b):
        calls.append((a, b))
        return real(a, b)

    monkeypatch.setattr(hmac, "compare_digest", spy)
    body = b'{"x":1}'
    sig = _sign(body, with_secret)
    webhook_auth.verify_tv_webhook_signature(body, sig)
    assert calls, "verify must use hmac.compare_digest, not =="
