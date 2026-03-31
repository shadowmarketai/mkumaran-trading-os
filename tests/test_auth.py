"""Tests for authentication — login, JWT, middleware, protected endpoints."""

from unittest.mock import patch

from mcp_server.auth import (
    hash_password,
    verify_password,
    create_access_token,
    decode_access_token,
    authenticate_admin,
)


# ── Password Hashing ──────────────────────────────────────


class TestPasswordHashing:
    def test_hash_roundtrip(self):
        plain = "testpass123"
        hashed = hash_password(plain)
        assert verify_password(plain, hashed) is True

    def test_wrong_password(self):
        hashed = hash_password("correct")
        assert verify_password("wrong", hashed) is False

    def test_hash_is_bcrypt(self):
        hashed = hash_password("test")
        assert hashed.startswith("$2b$")


# ── JWT Tokens ─────────────────────────────────────────────


class TestJWT:
    def test_create_and_decode(self):
        token = create_access_token({"sub": "admin@test.com", "role": "admin"})
        payload = decode_access_token(token)
        assert payload is not None
        assert payload["sub"] == "admin@test.com"
        assert payload["role"] == "admin"

    def test_expired_token(self):
        token = create_access_token({"sub": "admin@test.com"}, expires_minutes=-1)
        payload = decode_access_token(token)
        assert payload is None

    def test_invalid_token(self):
        payload = decode_access_token("not-a-valid-token")
        assert payload is None

    def test_tampered_token(self):
        token = create_access_token({"sub": "admin@test.com"})
        tampered = token[:-5] + "XXXXX"
        payload = decode_access_token(tampered)
        assert payload is None


# ── Admin Authentication ───────────────────────────────────


class TestAdminAuth:
    def test_successful_login(self):
        hashed = hash_password("mysecret")
        with patch("mcp_server.auth.settings") as mock_settings:
            mock_settings.ADMIN_EMAIL = "admin@test.com"
            mock_settings.ADMIN_PASSWORD_HASH = hashed
            mock_settings.JWT_SECRET_KEY = "test-secret"
            result = authenticate_admin("admin@test.com", "mysecret")
        assert result is not None
        assert result["email"] == "admin@test.com"
        assert result["role"] == "admin"

    def test_wrong_email(self):
        hashed = hash_password("mysecret")
        with patch("mcp_server.auth.settings") as mock_settings:
            mock_settings.ADMIN_EMAIL = "admin@test.com"
            mock_settings.ADMIN_PASSWORD_HASH = hashed
            result = authenticate_admin("wrong@test.com", "mysecret")
        assert result is None

    def test_wrong_password(self):
        hashed = hash_password("mysecret")
        with patch("mcp_server.auth.settings") as mock_settings:
            mock_settings.ADMIN_EMAIL = "admin@test.com"
            mock_settings.ADMIN_PASSWORD_HASH = hashed
            result = authenticate_admin("admin@test.com", "wrongpass")
        assert result is None

    def test_no_hash_configured(self):
        with patch("mcp_server.auth.settings") as mock_settings:
            mock_settings.ADMIN_EMAIL = "admin@test.com"
            mock_settings.ADMIN_PASSWORD_HASH = ""
            result = authenticate_admin("admin@test.com", "anything")
        assert result is None


# ── API Endpoint Tests (using TestClient) ──────────────────


class TestPublicEndpoints:
    """Public endpoints should always be accessible regardless of auth state."""

    def test_health_always_accessible(self):
        from fastapi.testclient import TestClient
        from mcp_server.mcp_server import app
        client = TestClient(app)
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_api_info_always_accessible(self):
        from fastapi.testclient import TestClient
        from mcp_server.mcp_server import app
        client = TestClient(app)
        resp = client.get("/api/info")
        assert resp.status_code == 200

    def test_login_endpoint_accessible(self):
        from fastapi.testclient import TestClient
        from mcp_server.mcp_server import app
        client = TestClient(app)
        # Login with wrong creds should return 401 (not 403 or blocked)
        resp = client.post("/auth/login", json={"email": "x", "password": "y"})
        assert resp.status_code == 401


class TestAuthDisabled:
    """When AUTH_ENABLED=false (default), all endpoints work without login."""

    def test_auth_me_returns_dev_user(self):
        from fastapi.testclient import TestClient
        from mcp_server.mcp_server import app
        # Default settings have AUTH_ENABLED=false
        client = TestClient(app)
        resp = client.get("/auth/me")
        assert resp.status_code == 200
        data = resp.json()
        assert data["auth_enabled"] is False
