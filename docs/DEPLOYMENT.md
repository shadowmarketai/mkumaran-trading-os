# Deployment — Secrets & Config

> Operator guide for deploying MKUMARAN Trading OS to production. Pairs with `.env.example` (which is the authoritative schema) and `README.md` (quick-start).
>
> **Last updated:** 2026-04-22

---

## TL;DR — minimum viable prod secrets

```bash
# ── MUST set (app refuses to boot without them in auth mode) ──
AUTH_ENABLED=true
JWT_SECRET_KEY=$(openssl rand -hex 32)
ADMIN_PASSWORD_HASH=$(python scripts/hash_password.py '<your-admin-password>')

# ── MUST set for the feature to work at all ──
DATABASE_URL=postgresql://trading:$(openssl rand -hex 16)@postgres:5432/trading_os
POSTGRES_PASSWORD=<same random value as above>

# ── Live trading (skip if PAPER_MODE=true) ──
KITE_API_KEY=...
KITE_API_SECRET=...
KITE_USER_ID=...
KITE_PASSWORD=...
KITE_TOTP_KEY=...        # base32 seed from Kite 2FA enrollment

# ── Alerts ──
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
ANTHROPIC_API_KEY=...    # or GROK_API_KEY / KIMI_API_KEY depending on AI_PRIMARY_PROVIDER

# ── NeuroLinked brain (omit to disable — bridge becomes a no-op) ──
NEUROLINKED_TOKEN=...    # tenant: trading_os. Request from brain.shadowmarket.ai ops.
```

---

## Required vs optional

| Category | Variable | Required? | Notes |
|---|---|---|---|
| **Auth** | `AUTH_ENABLED` | default `false` | Set `true` for prod. |
| | `JWT_SECRET_KEY` | **required when `AUTH_ENABLED=true`** | App **will refuse to start** if this is the placeholder `change-this-in-production`. Generate with `openssl rand -hex 32`. |
| | `ADMIN_EMAIL` | optional | Defaults to `sales@shadowmarket.ai`. |
| | `ADMIN_PASSWORD_HASH` | **required for first-boot admin login** | bcrypt hash — generate via `scripts/hash_password.py`. |
| | `JWT_EXPIRE_MINUTES` | optional | Default 480 (8 hours). |
| **DB** | `DATABASE_URL` | **required** | Format: `postgresql://user:pass@host:5432/db`. `postgres://` is auto-rewritten to `postgresql://` (`db.py:13`). |
| | `POSTGRES_PASSWORD` | **required** | Used by the `postgres` service in `docker-compose.yml`. |
| **Broker (Kite — primary)** | `KITE_API_KEY`, `KITE_API_SECRET`, `KITE_USER_ID`, `KITE_PASSWORD`, `KITE_TOTP_KEY` | **required for live trading** | Skip if `PAPER_MODE=true`. TOTP key is the base32 seed (not the 6-digit code). |
| | `KITE_REDIRECT_URL` | optional | Default `https://money.shadowmarket.ai/api/kite_callback`. Must match the redirect URL registered in the Kite Connect app. |
| **Broker (Dhan)** | `DHAN_TOTP_KEY`, `DHAN_PIN` | optional | When both are set, tokens auto-refresh via `dhan_auth.py`. Dhan is the MCX primary source and NFO/options fallback. |
| **Broker (Angel One)** | `ANGEL_API_KEY`, `ANGEL_API_SECRET`, `ANGEL_CLIENT_ID`, `ANGEL_PASSWORD`, `ANGEL_TOTP_SECRET` | optional | Secondary broker. |
| **Broker (Goodwill)** | `GWC_API_KEY`, `GWC_API_SECRET`, `GWC_CLIENT_ID`, `GWC_REDIRECT_URL`, `GOODWILL_PASSWORD`, `GOODWILL_TOTP_KEY` | optional | OAuth-based. |
| **AI providers** | `AI_PRIMARY_PROVIDER` | optional | `grok` (default), `kimi`, `anthropic`, `openai`. |
| | `GROK_API_KEY` / `KIMI_API_KEY` / `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` | **≥1 required** | Whichever matches `AI_PRIMARY_PROVIDER`. Debate validator uses whichever is configured. |
| | `AI_REPORT_MODEL` | optional | Default `claude-haiku-4-5-20251001`. Only used if Anthropic is configured. |
| **Alerts** | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | **required in practice** | Signal delivery mechanism. Bot must be in the chat. `TELEGRAM_SIGNALS_ONLY=true` by default. |
| **Google Sheets** | `GOOGLE_SHEET_ID` | optional | Enables accuracy-tracking auto-sync. |
| | `GOOGLE_SHEETS_CREDENTIALS` | optional | Defaults to `data/service_account.json`. |
| | `GOOGLE_SERVICE_ACCOUNT_JSON` | optional | Alternative to the file — inline JSON. `config.py:_bootstrap_service_account` writes it to disk at import. |
| **NeuroLinked brain** | `NEUROLINKED_TOKEN` | optional but recommended | Empty → bridge is disabled (silent no-op). Tenant: `trading_os`. |
| | `NEUROLINKED_URL` | optional | Default `https://brain.shadowmarket.ai`. |
| | `NEUROLINKED_ENABLED` | optional | Default `true`, but gated on `NEUROLINKED_TOKEN` being non-empty. |
| **n8n** | `N8N_WEBHOOK_BASE` | optional | Default `https://n8n.shadowmarket.ai`. Workflows in `n8n_workflows/` call back into this server. |
| **TradingView screener** | `TRADINGVIEW_SCANNER_ENABLED`, `TRADINGVIEW_SESSIONID`, `TRADINGVIEW_SESSIONID_SIGN` | optional | Augments Chartink. For real-time data paste your sessionid cookie. |
| **Intraday** | `INTRADAY_SIGNALS_ENABLED` | optional | Default `false` — opt-in. |
| **RRMS defaults** | `RRMS_CAPITAL`, `RRMS_RISK_PCT`, `RRMS_MIN_RRR` | optional | Per-user override happens via dashboard. |
| **Debate validator** | `DEBATE_ENABLED`, `DEBATE_UNCERTAIN_LOW`, `DEBATE_UNCERTAIN_HIGH`, `DEBATE_ROUNDS` | optional | Defaults in `config.py:112`. |
| **Email OTP** | `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS` | optional | For email-OTP login. |
| **Mobile OTP** | `MSG91_AUTH_KEY` | optional | For mobile-OTP login. |
| **Google OAuth** | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | optional | For Google sign-in. |

---

## Fail-closed checks at startup

The app actively refuses to boot in unsafe configurations:

1. **`AUTH_ENABLED=true` with placeholder JWT secret** → `RuntimeError` at import (`mcp_server/config.py:_fail_closed_secrets_check`).
   - Message: _"AUTH_ENABLED=true but JWT_SECRET_KEY is the placeholder default. Generate a strong secret with `openssl rand -hex 32` and set JWT_SECRET_KEY in your environment. Refusing to start."_
   - To fix: set `JWT_SECRET_KEY` to a random 64-hex-char value.

Additional runtime (non-fatal) warnings:
- `NEUROLINKED_ENABLED=true` but `NEUROLINKED_TOKEN` empty → `logger.warning` + bridge disables itself silently.

---

## Secret rotation

| Secret | Rotation cadence | How |
|---|---|---|
| `JWT_SECRET_KEY` | On compromise; otherwise every 6 months | `openssl rand -hex 32`; redeploy; all existing JWTs become invalid (users must log in again). |
| `KITE_TOTP_KEY`, `ANGEL_TOTP_SECRET`, `DHAN_TOTP_KEY`, `GOODWILL_TOTP_KEY` | On broker password change or compromise | Re-enroll 2FA in the broker portal; copy the fresh base32 seed. |
| Broker passwords / API keys | Per broker T&Cs (typically yearly) | Broker portal → regenerate → update env → redeploy. |
| `ANTHROPIC_API_KEY` / `GROK_API_KEY` / `KIMI_API_KEY` / `OPENAI_API_KEY` | On compromise or team exit | Provider console → revoke → generate → update env. |
| `TELEGRAM_BOT_TOKEN` | On compromise | `@BotFather` → `/revoke` → new token → update env. |
| `NEUROLINKED_TOKEN` | On compromise | Contact NeuroLinked brain ops. **One hardcoded fallback token was committed to git history prior to this PR (`brain_bridge.py`) — it has been removed from the source tree and must be revoked on the brain side.** |
| `ADMIN_PASSWORD_HASH` | On admin password change | `python scripts/hash_password.py '<new-password>'` → update env → redeploy. |
| `GOOGLE_SERVICE_ACCOUNT_JSON` / `data/service_account.json` | On key rotation (GCP policy) | GCP console → disable old key → create new → update env/volume. |

**Never commit secrets to git.** `.env` is `.gitignored`. Use Docker env vars, Coolify secret manager, or a vault in prod.

**If a secret appears in git history**, rotating it is necessary but not sufficient — also scrub history (`git filter-repo` or BFG) and force-push if the repo is already public. For public repos, assume any committed secret is compromised the moment it lands on `origin`.

---

## Deploy flow (Docker Compose)

```bash
# 1. Prepare env
cp .env.example .env
# Edit .env — set all REQUIRED vars from the table above

# 2. Validate locally
docker compose -f docker-compose.dev.yml up -d postgres
docker compose -f docker-compose.dev.yml up backend   # watch for the fail-closed check
# Ctrl+C once it boots cleanly

# 3. Deploy
docker compose up -d
docker compose logs -f backend | head -200            # confirm lifespan startup
curl -fsS http://localhost/health                     # expect 200 {"status":"ok"}

# 4. Smoke test
curl -fsS http://localhost/api/info
open http://localhost/                                # dashboard should render
```

**Rollback:** `docker compose down && docker compose up -d <previous-image-tag>`. No automated rollback.

---

## CI note

GitHub Actions (`.github/workflows/ci.yml`) runs with `AUTH_ENABLED=false` and `PAPER_MODE=true`, so the fail-closed JWT check is a no-op in CI. Any production-like verification needs a staging env with `AUTH_ENABLED=true` and a real (non-placeholder) `JWT_SECRET_KEY`.
