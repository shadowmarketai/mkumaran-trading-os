# MKUMARAN Trading OS

Automated personal trading intelligence for Indian markets. Multi-asset coverage across NSE, BSE, MCX, CDS, and NFO with 6 analysis engines, Claude AI validation, and full order management.

**Strategy**: TradingView + Zerodha Kite + Claude MCP + n8n automation

---

## Quick Start

### Prerequisites

- Docker & Docker Compose
- Zerodha Kite Connect account (for live trading)
- Anthropic API key (for signal validation)
- Telegram bot (for alerts)

### 1. Clone & Configure

```bash
git clone https://github.com/shadowmarketai/mkumaran-trading-os.git
cd mkumaran-trading-os
cp .env.example .env
```

Edit `.env` with your credentials:

```env
# Required
DATABASE_URL=postgresql://trading:trading_pass@postgres:5432/trading_os
POSTGRES_PASSWORD=trading_pass
ANTHROPIC_API_KEY=sk-ant-...

# Zerodha Kite (skip if using Paper Mode)
KITE_API_KEY=your_app_key
KITE_API_SECRET=your_secret
KITE_USER_ID=your_id
KITE_PASSWORD=your_password
KITE_TOTP_KEY=your_totp_seed

# Telegram alerts
TELEGRAM_BOT_TOKEN=123456:ABC...
TELEGRAM_CHAT_ID=-100...

# Google Sheets tracking (optional)
GOOGLE_SHEET_ID=your_sheet_id

# n8n automation (optional)
N8N_WEBHOOK_BASE=https://your-n8n.example.com
```

### 2. Start

```bash
docker compose up -d
```

This launches 3 services:

| Service | Port | Description |
|---------|------|-------------|
| **postgres** | 5432 (internal) | PostgreSQL 16 with schema auto-init |
| **backend** | 8001 (internal) | FastAPI MCP server (71 endpoints) |
| **dashboard** | 80 (public) | React dashboard via Nginx |

### 3. Verify

```bash
# Health check
curl http://localhost/health

# API docs
open http://localhost/docs

# Dashboard
open http://localhost/
```

---

## Paper Mode (No Kite Required)

Want to test without a Kite account? Add to your `.env`:

```env
PAPER_MODE=true
```

Paper mode:
- Uses in-memory positions with `PAPER-XXXXXX` order IDs
- All safety controls remain active (kill switch, position limits, trailing SL)
- Uses yfinance for market data (no Kite connection needed)
- Dashboard Paper Trading page works identically

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                        Dashboard (React)                         │
│  Overview │ Trades │ Paper │ Watchlist │ Backtest │ Options │ ... │
└──────────────────────┬───────────────────────────────────────────┘
                       │ HTTP/REST
┌──────────────────────▼───────────────────────────────────────────┐
│                    MCP Server (FastAPI)                           │
│                                                                   │
│  ┌─────────┐  ┌─────────┐  ┌──────────┐  ┌──────────────────┐   │
│  │ Scanners │  │ Engines │  │ Validator │  │  Order Manager   │   │
│  │ (82 x12) │  │(6 types)│  │(Claude AI)│  │(Kite / Paper)    │   │
│  └────┬─────┘  └────┬────┘  └─────┬─────┘  └────────┬────────┘   │
│       │             │             │                   │            │
│  ┌────▼─────────────▼─────────────▼───────────────────▼────────┐  │
│  │                    Data Provider                             │  │
│  │          Kite (primary) ←→ yfinance (fallback)              │  │
│  │               OHLCV Cache (PostgreSQL)                      │  │
│  └─────────────────────────────────────────────────────────────┘  │
└──────────┬─────────────┬──────────────┬───────────────────────────┘
           │             │              │
    ┌──────▼──┐   ┌──────▼──┐   ┌──────▼──────┐
    │PostgreSQL│   │Telegram │   │Google Sheets│
    │  (6 tbl) │   │  Bot    │   │  Auto-sync  │
    └─────────┘   └─────────┘   └─────────────┘
           │
    ┌──────▼──────────────────────────────┐
    │  n8n (4 workflows)                  │
    │  Morning │ Signals │ Monitor │ EOD  │
    └─────────────────────────────────────┘
```

### 6 Analysis Engines

| Engine | What It Detects |
|--------|----------------|
| **Pattern** | Flags, triangles, wedges, head & shoulders, double tops/bottoms |
| **SMC** | Order blocks, fair value gaps, break of structure, liquidity sweeps |
| **Wyckoff** | Accumulation/distribution phases, springs, upthrusts |
| **VSA** | Volume spread analysis — effort vs result, no demand, stopping volume |
| **Harmonic** | Gartley, butterfly, bat, crab, ABCD patterns |
| **RL** | Regime detection, VWAP deviation, momentum scoring, optimal entries |

### 5 Exchanges

| Exchange | Asset Class | Example Symbols |
|----------|------------|-----------------|
| NSE | Equity | `NSE:RELIANCE`, `NSE:TCS` |
| BSE | Equity | `BSE:INFY` |
| MCX | Commodity | `MCX:GOLD`, `MCX:CRUDEOIL`, `MCX:SILVER` |
| CDS | Currency | `CDS:USDINR`, `CDS:EURINR` |
| NFO | F&O | `NFO:NIFTY`, `NFO:BANKNIFTY` |

---

## Dashboard Pages

### Overview (`/overview`)
Market status, today's signals, MWA composite score, Nifty/BankNifty prices, active trade count.

### Active Trades (`/trades`)
All open positions with entry/SL/target, current price, P&L%, progress bars, RRR metrics.

### Paper Trading (`/paper`)
Place simulated orders, view open paper positions, monitor kill switch status, capital, daily P&L. Close individual positions or close all.

### Accuracy (`/accuracy`)
Win rate, profit factor, pattern-by-pattern breakdown, monthly P&L chart, direction stats.

### Watchlist (`/watchlist`)
Manage tracked tickers. Add/remove symbols, set tiers, toggle active scanning.

### Backtesting (`/backtesting`)
Run any of 6 strategy presets against any ticker. Compare all strategies side-by-side with equity curves and drawdown charts.

### Pattern Engines (`/engines`)
Run individual engines on any ticker. View detected patterns with confidence scores.

### Wall Street AI (`/wallstreet`)
Fundamental analysis — DCF valuation, earnings briefs, sector rotation, macro assessment.

### News & Macro (`/news`)
RSS + NewsAPI aggregation. HIGH/MEDIUM/LOW impact classification. Auto-alerts for market-moving events.

### Momentum (`/momentum`)
Momentum ranking of NSE universe (12M/6M/3M returns + inverse volatility). Rebalance signals.

### Options Greeks (`/options`)
Black-Scholes calculator. Full option chain with delta/gamma/theta/vega/rho + implied volatility.

### Payoff Calculator (`/payoff`)
Multi-leg options payoff diagrams. 6 presets: Bull Call Spread, Bear Put Spread, Long Straddle, Iron Condor, etc.

---

## Signal Flow (End-to-End)

Here's what happens when a trading signal is generated:

```
1. TradingView Alert fires
         │
         ▼
2. POST /api/tv_webhook receives Pine Script alert
         │
         ▼
3. MWA Scanner runs 82 scanners across 12 layers
   - Pattern flags, SMC order blocks, Wyckoff phases
   - Volume analysis, harmonic patterns, RL regime
   - Composite score calculated
         │
         ▼
4. Trade Memory (BM25) searches for similar past trades
   - Returns top-K most similar historical trades
   - Attaches win/loss context
         │
         ▼
5. Debate Validator (confidence 40-75%)
   - Bull case analyst generates arguments
   - Bear case analyst generates counter-arguments
   - Judge weighs both + risk assessment
   - Low/high confidence → single-pass validation
         │
         ▼
6. RRMS validates risk/reward
   - Min 3:1 RRR for equity, 2:1 for F&O/MCX/CDS
   - Position size = (Capital × 2%) / (Entry - SL)
   - Max 10% of capital per trade
         │
         ▼
7. Portfolio Risk check
   - Max 25% sector exposure
   - Max 50% asset-class exposure
   - Max 5 concurrent positions
         │
         ▼
8. Order placed via Kite (or Paper mode)
   - Kill switch check (blocks if daily loss > -3%)
   - Trailing SL activated after +3% profit
   - Partial exits at milestones
         │
         ▼
9. Notifications sent
   - Telegram alert with signal details
   - Google Sheets auto-sync
   - Dashboard updates in real-time
         │
         ▼
10. Post-trade reflection
    - Lesson generation on exit
    - Trade memory updated for future BM25 lookups
    - Accuracy metrics recalculated
```

---

## Order Manager Safety Controls

| Control | Setting | Description |
|---------|---------|-------------|
| **Kill Switch** | -3% daily loss | Blocks ALL new orders until next trading day |
| **Max Positions** | 5 concurrent | No new orders beyond limit |
| **Max Position Size** | 10% of capital | Single trade can't exceed this |
| **Trailing SL** | 2% trail distance | Activates after 3% profit, only moves favorably |
| **Partial Exits** | Milestone-based | TRAIL -> PARTIAL_50 -> PARTIAL_25 -> TRAIL_TIGHT |
| **Sector Cap** | 25% max | No more than 25% capital in one sector |
| **Asset Class Cap** | 50% max | No more than 50% in one asset class |
| **API Timeout** | 30 seconds | All Claude API calls fail-safe on timeout |
| **Market Hours** | Exchange-specific | Telegram alerts skip outside trading hours |

---

## n8n Automation Workflows

Import from `n8n_workflows/` directory into your n8n instance.

| Workflow | Trigger | What It Does |
|----------|---------|-------------|
| `00_morning_startup.json` | 8:45 AM IST | MWA scan, momentum ranking, Telegram summary |
| `01_signal_receiver.json` | TradingView webhook | Parse alert -> validate -> record -> notify |
| `02_market_monitor.json` | Every 30 min | News scan, macro events, HIGH-alert to Telegram |
| `03_eod_report.json` | 3:30 PM IST | Daily P&L, closed trades, reflection, rebalance |

---

## Authentication

Auth is **opt-in** (disabled by default). To enable:

```env
AUTH_ENABLED=true
ADMIN_EMAIL=your@email.com
ADMIN_PASSWORD_HASH=$2b$12$...    # bcrypt hash
JWT_SECRET_KEY=change-me-to-random-string
JWT_EXPIRE_MINUTES=480
```

Generate a password hash:
```python
import bcrypt
print(bcrypt.hashpw(b"your-password", bcrypt.gensalt()).decode())
```

Login at `/login` -> JWT token stored in localStorage -> auto-logout on 401.

---

## API Endpoints (71 total)

### Core Dashboard

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/api/info` | Server version & status |
| GET | `/api/overview` | Dashboard summary |
| GET | `/api/signals` | Recent signals |
| GET | `/api/trades/active` | Open positions |
| GET | `/api/mwa/latest` | Latest MWA score |
| GET | `/api/accuracy` | Win rate & stats |
| GET | `/api/exchanges` | Supported exchanges |

### Watchlist

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/watchlist` | List all |
| POST | `/api/watchlist` | Add ticker |
| PATCH | `/api/watchlist/{id}/toggle` | Toggle active |
| DELETE | `/api/watchlist/{id}` | Remove |

### Backtesting & Options

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/backtest` | Run single strategy |
| POST | `/api/backtest/compare` | Compare all strategies |
| POST | `/api/options/greeks` | Black-Scholes Greeks + IV |
| GET | `/api/options/chain` | Option chain |
| POST | `/api/options/payoff` | Multi-leg payoff diagram |

### Order Management

| Method | Path | Description |
|--------|------|-------------|
| POST | `/tools/place_order` | Place order (paper or live) |
| POST | `/tools/cancel_order` | Cancel pending order |
| POST | `/tools/close_position` | Close by ticker |
| POST | `/tools/close_all` | Emergency close all |
| GET | `/tools/order_status` | Kill switch + positions |
| POST | `/tools/update_pnl` | Feed daily P&L |

### Scanning & Engines

| Method | Path | Description |
|--------|------|-------------|
| POST | `/tools/run_mwa_scan` | Full 12-layer MWA scan |
| POST | `/tools/get_mwa_score` | Single ticker score |
| POST | `/tools/detect_pattern` | Pattern engine |
| POST | `/tools/detect_smc` | Smart Money Concepts |
| POST | `/tools/detect_wyckoff` | Wyckoff analysis |
| POST | `/tools/detect_vsa` | Volume Spread Analysis |
| POST | `/tools/detect_harmonic` | Harmonic patterns |
| POST | `/tools/detect_rl` | RL engine |
| POST | `/tools/validate_signal` | Claude AI validation |

### Integrations

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/tv_webhook` | TradingView alerts |
| POST | `/api/telegram_webhook` | Telegram signal receiver |
| GET | `/api/news` | News aggregation |
| GET | `/api/momentum` | Momentum rankings |
| POST | `/tools/momentum_rebalance` | Rebalance signals |

See full interactive docs at `http://your-server/docs` (Swagger UI).

---

## Running Tests

```bash
# All 791 tests
pytest -v

# Specific module
pytest tests/test_paper_trading.py -v
pytest tests/test_options_greeks.py -v
pytest tests/test_options_payoff.py -v

# With coverage
pytest --cov=mcp_server --cov-report=term-missing

# Fast subset
pytest -x -q  # stop on first failure, quiet
```

### Test Coverage by Module

| Test File | Tests | What It Covers |
|-----------|-------|---------------|
| `test_mcp_server.py` | 80+ | All API endpoints |
| `test_nse_scanner.py` | 100+ | 82 scanners + MWA scoring |
| `test_asset_registry.py` | 42 | Multi-exchange symbol resolution |
| `test_paper_trading.py` | 18 | Paper mode orders + safety |
| `test_options_greeks.py` | 22 | Black-Scholes + IV solver |
| `test_options_payoff.py` | 14 | Multi-leg payoff + breakevens |
| `test_backtest_compare.py` | 18 | Strategy comparison |
| `test_ohlcv_cache.py` | 32 | Cache freshness + purge |
| `test_data_provider.py` | 28 | Kite/yfinance fallback |
| `test_momentum_ranker.py` | 16 | Momentum scoring + rebalance |

---

## Development

### Local Dev (without Docker)

```bash
# Backend
pip install -r requirements.txt
uvicorn mcp_server.mcp_server:app --reload --port 8001

# Frontend (separate terminal)
cd dashboard
npm install
npm run dev    # localhost:5173, proxies /api to :8001
```

### Linting & Type Checking

```bash
# Python
ruff check mcp_server/ tests/

# TypeScript
cd dashboard
npm run lint
npm run type-check
```

### Database

PostgreSQL 16 with schema auto-loaded from `schema.sql` on first boot. Tables:

| Table | Purpose |
|-------|---------|
| `watchlist` | Tracked tickers with exchange/asset_class |
| `signal` | Scanner detections + confidence + AI validation |
| `outcome` | Exit records with P&L and lessons |
| `mwa_score` | Composite MWA scan results |
| `active_trade` | Open positions with SL/target/trailing state |
| `ohlcv_cache` | OHLCV bar cache with TTL staleness |

---

## Environment Variables Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DATABASE_URL` | Yes | — | PostgreSQL connection string |
| `KITE_API_KEY` | No | — | Zerodha app key |
| `KITE_API_SECRET` | No | — | Zerodha secret |
| `KITE_USER_ID` | No | — | Zerodha user ID |
| `KITE_PASSWORD` | No | — | Zerodha password |
| `KITE_TOTP_KEY` | No | — | TOTP seed for MFA |
| `ANTHROPIC_API_KEY` | Yes | — | Claude API key |
| `TELEGRAM_BOT_TOKEN` | No | — | Telegram bot token |
| `TELEGRAM_CHAT_ID` | No | — | Telegram chat ID |
| `GOOGLE_SHEET_ID` | No | — | Google Sheets ID |
| `N8N_WEBHOOK_BASE` | No | — | n8n base URL |
| `PAPER_MODE` | No | `false` | Enable paper trading |
| `AUTH_ENABLED` | No | `false` | Enable JWT auth |
| `RRMS_CAPITAL` | No | `100000` | Starting capital (INR) |
| `RRMS_RISK_PCT` | No | `0.02` | Risk per trade (2%) |
| `RRMS_MIN_RRR` | No | `3.0` | Min risk:reward ratio |
| `DEBATE_ENABLED` | No | `true` | Enable debate validator |
| `DATA_PROVIDER_PRIMARY` | No | `kite` | `kite` or `yfinance` |
| `OHLCV_CACHE_ENABLED` | No | `true` | Enable OHLCV cache |

---

## Key Numbers

| Metric | Value |
|--------|-------|
| API Endpoints | 71 |
| Scanners | 82 across 12 layers |
| Signal Chains | 23 |
| Analysis Engines | 6 |
| Supported Exchanges | 5 |
| Database Tables | 6 |
| n8n Workflows | 4 |
| Dashboard Pages | 12 |
| Tests | 791 across 45 files |

---

## Version History

| Version | Highlights |
|---------|-----------|
| **v2.6** | Paper Trading UI, Options Greeks, Payoff Calculator, Backtest Compare |
| **v2.5** | OHLCV cache layer (PostgreSQL, TTL-based) |
| **v2.4** | Unified data provider (Kite + yfinance fallback) |
| **v2.3** | Momentum ranking module |
| **v2.2** | Admin auth, Telegram market hours gate, News monitor |
| **v2.1** | Trailing SL, partial exits, debate validator, portfolio risk |
| **v1.9** | Debate validator + BM25 trade memory |
| **v1.8** | RL engine (6 detectors, 8 scanners) |
| **v1.7** | Full integrations (n8n, Kite, Sheets, TradingView, Telegram) |

---

Built by M. Kumaran | Shadow Market AI
