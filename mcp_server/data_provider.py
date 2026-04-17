"""
MKUMARAN Trading OS — Multi-Source Market Data Provider

Combines all Indian market data sources with automatic failover.

SOURCE PRIORITY:
  Live Quotes    : Goodwill API → NSE India → Angel SmartAPI
  Historical     : Angel SmartAPI → NSE India → Upstox → yfinance
  WebSocket      : Goodwill → Angel → Upstox
  FII/DII        : NSE India (only free source, no fallback needed)
  OI/Option Chain: NSE India (free, best source)
  Delivery %     : NSE India (free, India-exclusive)
  Order Placement: Goodwill API (your broker)

COST: ₹0/month — all sources either free or included with broker account

BACKWARD COMPATIBILITY:
  get_stock_data(ticker, period, interval) still works exactly as before.
  It now routes through the multi-source provider instead of Kite-only.

.env variables:
  GOODWILL_API_KEY, GOODWILL_CLIENT_ID, GOODWILL_PASSWORD, GOODWILL_TOTP_KEY
  ANGEL_API_KEY, ANGEL_CLIENT_ID, ANGEL_PIN, ANGEL_TOTP_KEY
  UPSTOX_API_KEY, UPSTOX_API_SECRET, UPSTOX_ACCESS_TOKEN
  DHAN_CLIENT_ID, DHAN_ACCESS_TOKEN
"""

import os
import time
import json
import logging
import requests
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta, date
from pathlib import Path
from typing import Optional, Dict
from functools import wraps

from mcp_server.asset_registry import parse_ticker, resolve_yf_symbol
from mcp_server.config import settings
from mcp_server.market_calendar import now_ist

logger = logging.getLogger(__name__)


# ── Backward-Compatible Mappings (used by tests) ─────────────────

_INTERVAL_MAP: dict[str, str] = {
    "1m": "minute",
    "3m": "3minute",
    "5m": "5minute",
    "10m": "10minute",
    "15m": "15minute",
    "30m": "30minute",
    "1h": "60minute",
    "1d": "day",
    "1wk": "week",
    "1mo": "month",
}

_PERIOD_TO_DAYS: dict[str, int] = {
    "1d": 1,
    "5d": 5,
    "1mo": 30,
    "3mo": 90,
    "6mo": 180,
    "1y": 365,
    "2y": 730,
    "5y": 1825,
}


# ── Segment-Aware Data Routing ──────────────────────────────
# Each segment lists data sources in priority order.
# Env-var override: DATA_ROUTE_MCX=angel,yfinance

SEGMENT_ROUTING: dict[str, list[str]] = {
    "NSE": ["angel", "nse", "dhan", "yfinance"],
    "BSE": ["angel", "nse", "dhan", "yfinance"],
    "NFO": ["angel", "kite", "dhan", "yfinance"],
    # MCX: ONLY real MCX FUTCOM contracts. yfinance is deliberately excluded
    # — it maps CRUDEOIL→CL=F (NYMEX WTI), GOLD→GC=F (COMEX), which are
    # global proxies in USD, NOT MCX FUTCOM in INR. Dhan added as primary
    # MCX source (free API, supports MCX_COMM segment natively).
    "MCX": ["dhan", "gwc", "angel", "kite"],
    "CDS": ["dhan", "angel", "kite", "yfinance"],
}

# Apply env-var overrides (e.g. DATA_ROUTE_MCX=angel,yfinance)
for _seg in list(SEGMENT_ROUTING):
    _env_key = f"DATA_ROUTE_{_seg}"
    _env_val = os.environ.get(_env_key, "")
    if _env_val:
        SEGMENT_ROUTING[_seg] = [s.strip() for s in _env_val.split(",") if s.strip()]
        logging.getLogger(__name__).info("Segment routing override %s=%s", _env_key, SEGMENT_ROUTING[_seg])


# ── Retry Decorator ──────────────────────────────────────────────

def retry(max_attempts: int = 3, delay: float = 1.0, no_retry: tuple = ()):
    """Retry decorator with exponential backoff.

    Args:
        max_attempts: Maximum attempts before giving up.
        delay: Base delay between retries (exponential backoff).
        no_retry: Tuple of exception types that should be re-raised immediately
                  without retrying (e.g. AngelTokenInvalid — the caller wants
                  to force-refresh the token, not retry the same broken call).
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except no_retry:
                    raise
                except Exception as e:
                    if attempt == max_attempts - 1:
                        raise
                    wait = delay * (2 ** attempt)
                    logger.warning(
                        "%s failed (attempt %d): %s. Retrying in %.1fs...",
                        func.__name__, attempt + 1, e, wait,
                    )
                    time.sleep(wait)
        return wrapper
    return decorator


# ══════════════════════════════════════════════════════════════════
# SOURCE 1 — NSE INDIA FREE API
# Free, no key needed, real-time during market hours
# Best for: Live quotes, FII/DII, OI, delivery %, 52-week data
# ══════════════════════════════════════════════════════════════════

class NSESource:

    BASE = "https://www.nseindia.com"
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.nseindia.com/",
    }

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)
        self._session_time = None
        self._init_session()

    def _init_session(self):
        """NSE requires homepage visit to set cookies."""
        try:
            self.session.get(f"{self.BASE}", timeout=10)
            self._session_time = datetime.now()
            logger.info("NSE session initialized")
        except Exception as e:
            logger.warning("NSE session init failed: %s", e)

    def _refresh_if_needed(self):
        """Refresh session every 30 minutes."""
        if not self._session_time or \
           (datetime.now() - self._session_time).seconds > 1800:
            self._init_session()

    @retry(max_attempts=3, delay=1.0)
    def get_quote(self, symbol: str) -> dict:
        self._refresh_if_needed()
        url = f"{self.BASE}/api/quote-equity?symbol={symbol.upper()}"
        resp = self.session.get(url, timeout=10)
        data = resp.json()
        pi = data.get("priceInfo", {})
        hl = pi.get("weekHighLow", {})
        return {
            "symbol": symbol,
            "source": "NSE",
            "ltp": pi.get("lastPrice", 0),
            "open": pi.get("open", 0),
            "high": pi.get("intraDayHighLow", {}).get("max", 0),
            "low": pi.get("intraDayHighLow", {}).get("min", 0),
            "prev_close": pi.get("previousClose", 0),
            "change": pi.get("change", 0),
            "pct_change": pi.get("pChange", 0),
            "volume": data.get("marketDeptOrderBook", {})
                         .get("tradeInfo", {})
                         .get("totalTradedVolume", 0),
            "52w_high": hl.get("max", 0),
            "52w_low": hl.get("min", 0),
        }

    @retry(max_attempts=2, delay=0.5)
    def get_historical(self, symbol: str,
                       from_date: str, to_date: str) -> pd.DataFrame:
        """Free historical EOD data from NSE. from_date, to_date: DD-MM-YYYY."""
        url = (f"{self.BASE}/api/historical/cm/equity"
               f"?symbol={symbol.upper()}&series=[%22EQ%22]"
               f"&from={from_date}&to={to_date}&csv=true")
        resp = self.session.get(url, timeout=15)

        # Guard: NSE may return HTML error pages instead of CSV
        text = resp.text.strip()
        if not text or text.startswith("<!") or text.startswith("<html"):
            logger.warning("NSE returned HTML instead of CSV for %s", symbol)
            return pd.DataFrame()

        from io import StringIO
        df = pd.read_csv(StringIO(text))
        if df.empty:
            return pd.DataFrame()

        df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]

        rename = {
            "date": "date", "open_price": "open", "high_price": "high",
            "low_price": "low", "close_price": "close",
            "total_traded_quantity": "volume",
            "open": "open", "high": "high", "low": "low",
            "close": "close", "volume": "volume",
            # NSE sometimes uses these column names
            "ch_timestamp": "date", "ch_opening_price": "open",
            "ch_trade_high_price": "high", "ch_trade_low_price": "low",
            "ch_closing_price": "close", "ch_total_traded_quantity": "volume",
            "HistoricalDate": "date",  # alternate JSON-sourced format
        }
        df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})

        # Find date column — try common names
        if "date" not in df.columns:
            date_candidates = [c for c in df.columns if "date" in c or "timestamp" in c]
            if date_candidates:
                df = df.rename(columns={date_candidates[0]: "date"})
            else:
                logger.warning("NSE CSV has no date column for %s. Columns: %s", symbol, list(df.columns))
                return pd.DataFrame()

        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date"])
        df = df.sort_values("date").reset_index(drop=True)

        needed = ["date", "open", "high", "low", "close", "volume"]
        avail = [c for c in needed if c in df.columns]
        return df[avail]

    @retry(max_attempts=2, delay=1.0)
    def get_fii_dii(self) -> dict:
        url = f"{self.BASE}/api/fiidiiTradeReact"
        resp = self.session.get(url, timeout=10)
        data = resp.json()
        result = {"date": str(date.today()), "fii_net": 0, "dii_net": 0, "source": "NSE"}
        for item in data:
            category = item.get("category", "").upper()
            net_val = float(str(item.get("netValue", "0")).replace(",", ""))
            if "FII" in category or "FPI" in category:
                result["fii_net"] += net_val
            elif "DII" in category:
                result["dii_net"] += net_val
        result["fii_buying"] = result["fii_net"] > 0
        result["dii_buying"] = result["dii_net"] > 0
        return result

    @retry(max_attempts=2, delay=1.0)
    def get_option_chain(self, symbol: str = "NIFTY") -> dict:
        """Full option chain with OI data — free."""
        if symbol in ("NIFTY", "BANKNIFTY", "FINNIFTY"):
            url = f"{self.BASE}/api/option-chain-indices?symbol={symbol}"
        else:
            url = f"{self.BASE}/api/option-chain-equities?symbol={symbol}"
        resp = self.session.get(url, timeout=15)
        return resp.json()

    @retry(max_attempts=2, delay=1.0)
    def get_delivery_pct(self, symbol: str) -> dict:
        """Delivery percentage — India-exclusive signal."""
        url = (f"{self.BASE}/api/quote-equity"
               f"?symbol={symbol.upper()}&section=trade_info")
        resp = self.session.get(url, timeout=10)
        data = resp.json()
        ti = data.get("securityWiseDP", {})
        pct = ti.get("deliveryToTradedQuantity", 0)
        try:
            pct = float(str(pct).replace("%", ""))
        except Exception:
            pct = 0
        return {
            "symbol": symbol,
            "delivery_pct": pct,
            "delivery_qty": ti.get("deliveryQuantity", 0),
            "traded_qty": ti.get("quantityTraded", 0),
            "high_delivery": pct >= 60,
        }

    @retry(max_attempts=2, delay=1.0)
    def get_52week_stocks(self) -> dict:
        """All stocks at 52-week high/low today."""
        high_url = f"{self.BASE}/api/live-analysis-52Week-high-low-limit?index=52WeekHigh"
        low_url = f"{self.BASE}/api/live-analysis-52Week-high-low-limit?index=52WeekLow"
        highs = self.session.get(high_url, timeout=10).json().get("data", [])
        lows = self.session.get(low_url, timeout=10).json().get("data", [])
        return {
            "52w_highs": [s.get("symbol", "") for s in highs],
            "52w_lows": [s.get("symbol", "") for s in lows],
            "high_count": len(highs),
            "low_count": len(lows),
        }

    @retry(max_attempts=2, delay=1.0)
    def get_bulk_deals(self) -> list:
        url = f"{self.BASE}/api/block-deal"
        resp = self.session.get(url, timeout=10)
        return resp.json().get("data", [])

    def get_pcr(self, symbol: str = "NIFTY") -> dict:
        """Calculate Put-Call Ratio from option chain."""
        oc = self.get_option_chain(symbol)
        records = oc.get("records", {}).get("data", [])
        call_oi = sum(r.get("CE", {}).get("openInterest", 0) for r in records if "CE" in r)
        put_oi = sum(r.get("PE", {}).get("openInterest", 0) for r in records if "PE" in r)
        pcr = round(put_oi / max(call_oi, 1), 2)
        return {
            "symbol": symbol,
            "pcr": pcr,
            "call_oi": call_oi,
            "put_oi": put_oi,
            "sentiment": "BULLISH" if pcr > 1.3 else "BEARISH" if pcr < 0.7 else "NEUTRAL",
        }


# ══════════════════════════════════════════════════════════════════
# SOURCE 2 — GOODWILL API (YOUR BROKER)
# Free for GWC account holders. Best for: orders, live quotes, WebSocket
# ══════════════════════════════════════════════════════════════════

class GoodwillSource:

    BASE = "https://api.gwcindia.in/v1"
    GIGA_BASE = "https://giga.gwcindia.in"

    def __init__(self):
        self.api_key = settings.GWC_API_KEY or os.environ.get("GOODWILL_API_KEY", "")
        self.api_secret = settings.GWC_API_SECRET
        self.client_id = settings.GWC_CLIENT_ID or os.environ.get("GOODWILL_CLIENT_ID", "")
        self.access_token = None
        self.session = requests.Session()
        self.logged_in = False
        self._token_map: dict[str, str] = {}  # SYMBOL -> numeric token
        self._token_map_date: str | None = None

    def login(self) -> bool:
        """Auto-login via gwc_auth.refresh_gwc_token (direct /v1/quickauth +
        /v1/login-response flow, no browser, no SMS OTP)."""
        if not self.api_key:
            logger.warning("GWC_API_KEY not set — skipping Goodwill login")
            return False
        try:
            from mcp_server.gwc_auth import refresh_gwc_token
            self.access_token = refresh_gwc_token()
            self.logged_in = True
            logger.info("Goodwill login OK (auto-login)")
            return True
        except Exception as e:
            logger.warning("Goodwill auto-login failed: %s", e)
            return False

    def set_access_token(self, token: str) -> None:
        """Inject access token from OAuth callback (no TOTP needed)."""
        self.access_token = token
        self.logged_in = True
        logger.info("Goodwill access token set via OAuth callback")

    def _headers(self) -> dict:
        return {
            "x-api-key": self.api_key,
            "Authorization": f"Bearer {self.access_token}",
        }

    # ── Instrument Token Map ────────────────────────────────────

    def _load_token_map(self) -> None:
        """Download NSE symbol→token map from GWC (daily reload)."""
        today = str(date.today())
        if self._token_map_date == today and self._token_map:
            return

        cache_path = Path("data/gwc_instruments.json")

        # Try loading from local cache first
        if cache_path.exists():
            try:
                cached = json.loads(cache_path.read_text())
                if cached.get("date") == today:
                    self._token_map = cached.get("map", {})
                    self._token_map_date = today
                    logger.info("GWC token map loaded from cache: %d symbols", len(self._token_map))
                    return
            except Exception:
                pass

        # Download fresh from GWC
        try:
            import zipfile
            from io import BytesIO
            resp = requests.get(f"{self.GIGA_BASE}/NSE_symbols.txt.zip", timeout=15)
            resp.raise_for_status()
            with zipfile.ZipFile(BytesIO(resp.content)) as zf:
                for name in zf.namelist():
                    if name.endswith(".txt"):
                        lines = zf.read(name).decode("utf-8").strip().split("\n")
                        break
                else:
                    lines = []

            token_map = {}
            for line in lines[1:]:  # skip header
                parts = line.strip().split(",")
                if len(parts) >= 2:
                    # Format: token,symbol,...
                    token_map[parts[1].strip().upper()] = parts[0].strip()

            if token_map:
                self._token_map = token_map
                self._token_map_date = today
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(json.dumps({"date": today, "map": token_map}))
                logger.info("GWC token map downloaded: %d symbols", len(token_map))
        except Exception as e:
            logger.warning("GWC token map download failed: %s", e)

    def _resolve_gwc_token(self, symbol: str) -> str | None:
        """Resolve symbol to GWC numeric token."""
        self._load_token_map()
        token = self._token_map.get(symbol.upper())
        if token:
            return token

        # Fallback: fetch individual symbol
        if not self.logged_in:
            return None
        try:
            resp = self.session.post(
                f"{self.BASE}/fetchsymbol",
                headers=self._headers(),
                json={"s": symbol.upper()},
                timeout=10,
            )
            data = resp.json()
            if data.get("status") == "success" and data.get("data"):
                tok = str(data["data"][0].get("token", ""))
                if tok:
                    self._token_map[symbol.upper()] = tok
                    return tok
        except Exception as e:
            logger.debug("GWC fetchsymbol failed for %s: %s", symbol, e)
        return None

    # ── Quote ───────────────────────────────────────────────────

    @retry(max_attempts=2, delay=1.0)
    def get_quote(self, exchange: str, symbol: str) -> dict:
        token = self._resolve_gwc_token(symbol)
        if not token:
            return {}
        resp = self.session.post(
            f"{self.BASE}/getquote",
            headers=self._headers(),
            json={"exchange": exchange, "token": token},
            timeout=10,
        )
        data = resp.json()
        if data.get("status") == "success":
            d = data["data"]
            return {
                "symbol": symbol,
                "exchange": exchange,
                "source": "GOODWILL",
                "ltp": float(d.get("ltp", d.get("lp", 0))),
                "open": float(d.get("open", d.get("o", 0))),
                "high": float(d.get("high", d.get("h", 0))),
                "low": float(d.get("low", d.get("l", 0))),
                "prev_close": float(d.get("close", d.get("c", 0))),
                "volume": int(d.get("volume", d.get("v", 0))),
                "pct_change": float(d.get("pct_change", d.get("pChange", 0))),
            }
        return {}

    @retry(max_attempts=2, delay=0.5)
    def place_order(self, exchange: str, symbol: str,
                    action: str, qty: int,
                    price: float = 0,
                    order_type: str = "MKT",
                    product: str = "MIS") -> dict:
        resp = self.session.post(
            f"{self.BASE}/placeOrder",
            headers=self._headers(),
            json={
                "exchange": exchange,
                "symbol": symbol,
                "action": action,
                "quantity": qty,
                "price": price,
                "order_type": order_type,
                "product": product,
            },
            timeout=10,
        )
        return resp.json()

    def get_positions(self) -> list:
        resp = self.session.get(f"{self.BASE}/position",
                                headers=self._headers(), timeout=10)
        return resp.json().get("data", [])

    def get_holdings(self) -> list:
        resp = self.session.get(f"{self.BASE}/holdings",
                                headers=self._headers(), timeout=10)
        return resp.json().get("data", [])

    def get_balance(self) -> dict:
        resp = self.session.get(f"{self.BASE}/balance",
                                headers=self._headers(), timeout=10)
        return resp.json().get("data", {})

    def get_orders(self) -> list:
        resp = self.session.get(f"{self.BASE}/orderBook",
                                headers=self._headers(), timeout=10)
        return resp.json().get("data", [])

    def start_websocket(self, symbols: list, on_tick):
        """Real-time WebSocket tick streaming."""
        import websocket as ws_lib

        def on_message(ws, message):
            on_tick(json.loads(message))

        def on_open(ws):
            ws.send(json.dumps({
                "action": "subscribe",
                "symbols": symbols,
                "token": self.access_token,
                "api_key": self.api_key,
            }))
            logger.info("Goodwill WebSocket: subscribed to %d symbols", len(symbols))

        def on_error(ws, error):
            logger.error("Goodwill WebSocket error: %s", error)

        def on_close(ws, *args):
            logger.warning("Goodwill WebSocket closed — reconnecting...")
            time.sleep(5)
            self.start_websocket(symbols, on_tick)

        wsapp = ws_lib.WebSocketApp(
            "wss://api.gwcindia.in/v1/websocket",
            on_open=on_open, on_message=on_message,
            on_error=on_error, on_close=on_close,
        )
        wsapp.run_forever()


# ══════════════════════════════════════════════════════════════════
# SOURCE 3 — ANGEL ONE SMARTAPI
# Free for Angel account holders. Best for: historical OHLCV
# ══════════════════════════════════════════════════════════════════

class AngelTokenInvalid(Exception):
    """Raised when Angel SmartAPI returns an Invalid Token (AG8001) error.

    Caught by MarketDataProvider._angel_fetch_with_refresh to trigger a
    mid-day TOTP re-login via force_refresh_angel_token().
    """
    pass


def _is_angel_token_error(payload: dict | str | None) -> bool:
    """Detect Angel SmartAPI Invalid Token / auth errors from any response shape."""
    if payload is None:
        return False
    if isinstance(payload, dict):
        text = " ".join(
            str(payload.get(k, "")) for k in ("message", "errorcode", "errorCode", "error")
        ).lower()
    else:
        text = str(payload).lower()
    return (
        "invalid token" in text
        or "ag8001" in text
        or "ag8002" in text
        or "unauthorized" in text
        or "session expired" in text
    )


class AngelSource:

    INTERVAL_MAP = {
        "1minute": "ONE_MINUTE",
        "5minute": "FIVE_MINUTE",
        "15minute": "FIFTEEN_MINUTE",
        "30minute": "THIRTY_MINUTE",
        "60minute": "ONE_HOUR",
        "day": "ONE_DAY",
    }

    # Product mapping: Kite-style → Angel SmartAPI
    PRODUCT_MAP = {
        "CNC": "DELIVERY",
        "MIS": "INTRADAY",
        "NRML": "CARRYFORWARD",
        "DELIVERY": "DELIVERY",
        "INTRADAY": "INTRADAY",
        "CARRYFORWARD": "CARRYFORWARD",
    }

    # Order type mapping: Kite-style → Angel SmartAPI
    ORDER_TYPE_MAP = {
        "MARKET": "MARKET",
        "LIMIT": "LIMIT",
        "SL": "STOPLOSS_LIMIT",
        "SL-M": "STOPLOSS_MARKET",
        "STOPLOSS_LIMIT": "STOPLOSS_LIMIT",
        "STOPLOSS_MARKET": "STOPLOSS_MARKET",
    }

    def __init__(self):
        from mcp_server.config import settings as _settings
        self.api_key = _settings.ANGEL_API_KEY
        self.client = None
        self.logged_in = False
        self._token_cache: Dict[str, str] = {}
        # Circuit breaker: after this many consecutive AG8001 / invalid-token
        # responses, the source self-disables for the rest of the session.
        # Prevents the scan loop from doing N × TOTP-login when Angel's IP
        # whitelist is rejecting our server.
        self._consecutive_failures = 0
        self._failure_threshold = 5
        # Sticky flag: once True, stays True for the lifetime of the process.
        # The auto-scan loop calls force_refresh_angel_token() and resets
        # logged_in=True before each cycle — this flag survives that so the
        # source remains disabled even after the JWT is refreshed (the JWT is
        # cosmetically valid but the upstream IP whitelist still rejects it).
        self._session_disabled = False

    def is_disabled(self) -> bool:
        """True once the session-level circuit breaker has tripped."""
        return self._session_disabled

    def trip_breaker(self, reason: str) -> None:
        """Force the session-level breaker open immediately.

        Called by MarketDataProvider after a force-refresh retry still returns
        AG8001 — that's a terminal state (IP whitelist issue), not transient.
        """
        if self._session_disabled:
            return
        logger.error(
            "AngelSource: session circuit breaker tripped — "
            "disabling for session (reason: %s)",
            reason,
        )
        self._session_disabled = True
        self.logged_in = False

    def _note_failure(self, reason: str) -> None:
        """Record a token failure; disable the source if threshold exceeded."""
        self._consecutive_failures += 1
        if self._consecutive_failures >= self._failure_threshold and not self._session_disabled:
            logger.error(
                "AngelSource: %d consecutive AG8001/token failures — "
                "disabling for session (last: %s)",
                self._consecutive_failures, reason,
            )
            self._session_disabled = True
            self.logged_in = False

    def _note_success(self) -> None:
        """Reset the failure counter after a successful call.

        Note: a success cannot un-trip the session-level breaker. Once Angel
        has been deemed unusable for the session it stays unusable until the
        process restarts (Angel IP whitelist is environmental, not transient).
        """
        if self._consecutive_failures:
            self._consecutive_failures = 0

    def login(self) -> bool:
        if not self.api_key:
            logger.warning("ANGEL_API_KEY not set — skipping Angel login")
            return False
        try:
            from mcp_server.angel_auth import get_authenticated_angel
            self.client = get_authenticated_angel()
            self.logged_in = True
            logger.info("Angel SmartAPI login OK (via angel_auth)")
            return True
        except ImportError:
            logger.warning("smartapi-python not installed: pip install smartapi-python")
        except Exception as e:
            logger.warning("Angel login error: %s", e)
        return False

    # ── Broker methods ───────────────────────────────────────

    def place_order(
        self,
        exchange: str,
        symbol: str,
        action: str,
        qty: int,
        price: float = 0,
        order_type: str = "LIMIT",
        product: str = "CNC",
        trigger_price: float = 0,
        variety: str = "NORMAL",
    ) -> dict:
        """Place an order via Angel SmartAPI."""
        if not self.logged_in or not self.client:
            return {"success": False, "message": "Angel not connected"}

        token = self._get_token(symbol, exchange)
        if not token:
            return {"success": False, "message": f"Symbol token not found for {symbol}"}

        order_params = {
            "variety": variety,
            "tradingsymbol": symbol,
            "symboltoken": token,
            "transactiontype": action,
            "exchange": exchange,
            "ordertype": self.ORDER_TYPE_MAP.get(order_type, order_type),
            "producttype": self.PRODUCT_MAP.get(product, product),
            "duration": "DAY",
            "price": str(price) if order_type != "MARKET" else "0",
            "triggerprice": str(trigger_price),
            "quantity": str(qty),
        }

        try:
            resp = self.client.placeOrder(order_params)
            if resp:
                return {"success": True, "order_id": str(resp), "message": "Order placed via Angel"}
            return {"success": False, "message": f"Angel placeOrder returned: {resp}"}
        except Exception as e:
            return {"success": False, "message": f"Angel order failed: {e}"}

    def cancel_order(self, order_id: str, variety: str = "NORMAL") -> dict:
        """Cancel an order via Angel SmartAPI."""
        if not self.logged_in or not self.client:
            return {"success": False, "message": "Angel not connected"}
        try:
            resp = self.client.cancelOrder(order_id, variety)
            return {"success": True, "order_id": order_id, "message": f"Cancelled: {resp}"}
        except Exception as e:
            return {"success": False, "message": f"Cancel failed: {e}"}

    def get_positions(self) -> dict:
        """Get current positions from Angel."""
        if not self.logged_in or not self.client:
            return {}
        try:
            return self.client.position() or {}
        except Exception as e:
            logger.warning("Angel positions error: %s", e)
            return {}

    def get_holdings(self) -> dict:
        """Get holdings from Angel."""
        if not self.logged_in or not self.client:
            return {}
        try:
            return self.client.holding() or {}
        except Exception as e:
            logger.warning("Angel holdings error: %s", e)
            return {}

    def get_balance(self) -> dict:
        """Get RMS/margin data from Angel."""
        if not self.logged_in or not self.client:
            return {}
        try:
            return self.client.rms() or {}
        except Exception as e:
            logger.warning("Angel balance error: %s", e)
            return {}

    def get_orders(self) -> dict:
        """Get order book from Angel."""
        if not self.logged_in or not self.client:
            return {}
        try:
            return self.client.orderBook() or {}
        except Exception as e:
            logger.warning("Angel orderBook error: %s", e)
            return {}

    def _get_token(self, symbol: str, exchange: str = "NSE") -> Optional[str]:
        """Get instrument token for symbol (cached).

        Raises AngelTokenInvalid if the JWT has expired so the caller can
        trigger a mid-day force refresh. Also bumps the session-level
        failure counter so a fully rejected source auto-disables.
        """
        if self._session_disabled or not self.logged_in:
            return None
        key = f"{exchange}:{symbol}"
        if key in self._token_cache:
            return self._token_cache[key]
        try:
            data = self.client.searchScrip(exchange, symbol)
        except Exception as e:
            if _is_angel_token_error(str(e)):
                self.trip_breaker(f"searchScrip {symbol} AG8001 (raised): {e}")
                raise AngelTokenInvalid(f"Angel token invalid during searchScrip: {e}") from e
            return None
        # searchScrip returns {"status": False, "message": "Invalid Token", ...}
        # or {"success": False, ...} when the JWT has expired — no exception is
        # raised by some SDK versions, so we detect it from the response dict.
        if isinstance(data, dict) and _is_angel_token_error(data):
            self.trip_breaker(f"searchScrip {symbol} AG8001: {data.get('message')}")
            raise AngelTokenInvalid(
                f"Angel searchScrip returned invalid token: {data.get('message')}"
            )
        # Some SDK versions return a generic failure dict (status/success False)
        # without explicit "Invalid Token" text when Angel rejects the IP.
        # Treat any {"status": False} / {"success": False} with empty data as
        # a terminal auth failure and trip the session breaker.
        if isinstance(data, dict) and (
            data.get("status") is False or data.get("success") is False
        ) and not data.get("data"):
            self.trip_breaker(
                f"searchScrip {symbol} rejected: {data.get('message') or data}"
            )
            raise AngelTokenInvalid(
                f"Angel searchScrip rejected (likely AG8001/whitelist): "
                f"{data.get('message') or data}"
            )
        if data and data.get("data"):
            candidates = data["data"]
            chosen = self._pick_instrument(candidates, symbol, exchange)
            if chosen is None:
                logger.debug(
                    "Angel: no matching instrument for %s on %s (searchScrip returned %d rows)",
                    symbol, exchange, len(candidates),
                )
                return None
            token = chosen.get("symboltoken")
            if not token:
                return None
            self._token_cache[key] = token
            self._note_success()
            return token
        return None

    # Allowed Angel instrumenttype per exchange. For derivatives we only want
    # the *futures* contracts (not options on the same underlying) so MCX
    # crude resolves to FUTCOM, not OPTFUT, NFO stock/index to FUTSTK/FUTIDX,
    # CDS currency to FUTCUR.
    _INSTRUMENT_TYPE_BY_EXCHANGE = {
        "MCX": ("FUTCOM",),
        "NFO": ("FUTSTK", "FUTIDX"),
        "BFO": ("FUTSTK", "FUTIDX"),
        "CDS": ("FUTCUR",),
    }

    @staticmethod
    def _parse_angel_expiry(exp: str) -> date:
        """Parse Angel expiry strings. Returns date.max on failure (sort last)."""
        if not exp:
            return date.max
        for fmt in ("%d%b%Y", "%d-%b-%Y", "%Y-%m-%d", "%d%b%y"):
            try:
                return datetime.strptime(exp.upper(), fmt).date()
            except Exception:
                continue
        return date.max

    def _pick_instrument(
        self, candidates: list, symbol: str, exchange: str
    ) -> Optional[dict]:
        """
        Filter searchScrip results to the correct contract.

        For MCX/NFO/CDS we require:
          1. instrumenttype in the allowed set for that exchange (FUTCOM for
             MCX, FUTSTK/FUTIDX for NFO, FUTCUR for CDS) so we never pick an
             option (OPTFUT/OPTSTK/OPTIDX/OPTCUR) when the caller asked for
             the underlying.
          2. name exactly matches the requested symbol (case-insensitive) to
             prevent partial matches ("CRUDEOILM" when asking "CRUDEOIL").
          3. Nearest non-expired expiry wins (current-month contract).

        For equity exchanges (NSE/BSE) we just take the first match as before.
        """
        if not candidates:
            return None

        allowed_types = self._INSTRUMENT_TYPE_BY_EXCHANGE.get(exchange)
        if not allowed_types:
            # Equity or unknown exchange — preserve old behaviour
            return candidates[0]

        sym_u = symbol.upper()

        # Primary: exact name + allowed instrumenttype
        exact = [
            c for c in candidates
            if c.get("instrumenttype") in allowed_types
            and (c.get("name") or "").upper() == sym_u
        ]
        pool = exact
        if not pool:
            # Fall back to instrumenttype filter only (name may differ slightly)
            pool = [
                c for c in candidates
                if c.get("instrumenttype") in allowed_types
            ]
        if not pool:
            return None

        today_d = date.today()
        future = [c for c in pool if self._parse_angel_expiry(c.get("expiry", "")) >= today_d]
        final = future or pool
        final.sort(key=lambda c: self._parse_angel_expiry(c.get("expiry", "")))
        return final[0]

    @retry(max_attempts=3, delay=1.0, no_retry=(AngelTokenInvalid,))
    def get_historical(self, symbol: str,
                       interval: str = "day",
                       days: int = 60,
                       exchange: str = "NSE") -> pd.DataFrame:
        """Historical OHLCV — best free source.

        Raises AngelTokenInvalid when the JWT is expired, so the caller can
        trigger a mid-day force refresh via force_refresh_angel_token().
        """
        if self._session_disabled or not self.logged_in:
            return pd.DataFrame()

        token = self._get_token(symbol, exchange)
        if not token:
            logger.warning("Angel: no token found for %s", symbol)
            return pd.DataFrame()

        from_dt = (now_ist() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M")
        to_dt = now_ist().strftime("%Y-%m-%d %H:%M")

        try:
            data = self.client.getCandleData({
                "exchange": exchange,
                "symboltoken": token,
                "interval": self.INTERVAL_MAP.get(interval, "ONE_DAY"),
                "fromdate": from_dt,
                "todate": to_dt,
            })
        except Exception as e:
            if _is_angel_token_error(str(e)):
                self.trip_breaker(f"getCandleData {symbol} AG8001 (raised): {e}")
                raise AngelTokenInvalid(
                    f"Angel token invalid during getCandleData: {e}"
                ) from e
            raise

        if isinstance(data, dict) and _is_angel_token_error(data):
            self.trip_breaker(f"getCandleData {symbol} AG8001: {data.get('message')}")
            raise AngelTokenInvalid(
                f"Angel getCandleData returned invalid token: {data.get('message')}"
            )

        if not data or not data.get("data"):
            return pd.DataFrame()

        df = pd.DataFrame(data["data"],
                          columns=["date", "open", "high", "low", "close", "volume"])
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
        self._note_success()
        return df

    @retry(max_attempts=2, delay=1.0, no_retry=(AngelTokenInvalid,))
    def get_quote(self, symbol: str, exchange: str = "NSE") -> dict:
        if self._session_disabled or not self.logged_in:
            return {}
        try:
            token = self._get_token(symbol, exchange)
            if not token:
                return {}
            data = self.client.ltpData(exchange, symbol, token)
        except AngelTokenInvalid:
            # Already noted via _get_token; propagate so caller breakers trip.
            raise
        except Exception as e:
            if _is_angel_token_error(str(e)):
                self.trip_breaker(f"ltpData {symbol} AG8001 (raised): {e}")
            return {}
        if isinstance(data, dict) and _is_angel_token_error(data):
            self.trip_breaker(f"ltpData {symbol} AG8001: {data.get('message')}")
            return {}
        try:
            ltp = data["data"]["ltp"] if data else 0
            if ltp:
                self._note_success()
            return {"symbol": symbol, "source": "ANGEL", "ltp": ltp}
        except Exception:
            return {}


# ══════════════════════════════════════════════════════════════════
# SOURCE 4 — UPSTOX API
# Free for Upstox account holders. Good fallback for historical
# ══════════════════════════════════════════════════════════════════

class UpstoxSource:

    INTERVAL_MAP = {
        "1minute": "1minute",
        "5minute": "5minute",
        "15minute": "15minute",
        "30minute": "30minute",
        "60minute": "60minute",
        "day": "day",
    }

    def __init__(self):
        self.api_key = os.environ.get("UPSTOX_API_KEY", "")
        self.client = None
        self.quote_client = None
        self.logged_in = False

    def login(self, access_token: str = None) -> bool:
        token = access_token or os.environ.get("UPSTOX_ACCESS_TOKEN", "")
        if not token:
            logger.warning("UPSTOX_ACCESS_TOKEN not set — skipping Upstox")
            return False
        try:
            import upstox_client
            config = upstox_client.Configuration()
            config.access_token = token
            api_client = upstox_client.ApiClient(config)
            self.client = upstox_client.HistoryApi(api_client)
            self.quote_client = upstox_client.MarketQuoteApi(api_client)
            self.logged_in = True
            logger.info("Upstox login OK")
            return True
        except ImportError:
            logger.warning("upstox-python-sdk not installed: pip install upstox-python-sdk")
        except Exception as e:
            logger.warning("Upstox login error: %s", e)
        return False

    @retry(max_attempts=2, delay=1.0)
    def get_historical(self, symbol: str,
                       interval: str = "day",
                       days: int = 60) -> pd.DataFrame:
        if not self.logged_in:
            return pd.DataFrame()
        try:
            from_date = (date.today() - timedelta(days=days)).strftime("%Y-%m-%d")
            to_date = date.today().strftime("%Y-%m-%d")
            instrument = f"NSE_EQ|{symbol}"
            resp = self.client.get_historical_candle_data1(
                instrument, self.INTERVAL_MAP.get(interval, "day"),
                to_date, from_date, "2.0"
            )
            candles = resp.data.candles
            df = pd.DataFrame(candles,
                              columns=["date", "open", "high", "low", "close", "volume", "oi"])
            df["date"] = pd.to_datetime(df["date"])
            df = df[["date", "open", "high", "low", "close", "volume"]]
            return df.sort_values("date").reset_index(drop=True)
        except Exception as e:
            logger.warning("Upstox historical failed for %s: %s", symbol, e)
            return pd.DataFrame()

    @retry(max_attempts=2, delay=0.5)
    def get_quote(self, symbol: str) -> dict:
        if not self.logged_in:
            return {}
        try:
            resp = self.quote_client.get_full_market_quote(
                f"NSE_EQ|{symbol}", "2.0"
            )
            ltp = resp.data[f"NSE_EQ:{symbol}"].last_price
            return {"symbol": symbol, "source": "UPSTOX", "ltp": ltp}
        except Exception:
            return {}


# ══════════════════════════════════════════════════════════════════
# SOURCE 5 — DHAN API
# Free for Dhan account holders. Simple clean API.
# ══════════════════════════════════════════════════════════════════

class DhanSource:

    # Exchange segment mapping: our internal codes → Dhan SDK constants.
    # The constants are class-level strings on the dhanhq object itself
    # (e.g. dhanhq.MCX == "MCX_COMM"), so we carry the string values here
    # so they work even before login.
    EXCHANGE_MAP: dict[str, str] = {
        "NSE": "NSE_EQ",
        "BSE": "BSE_EQ",
        "NFO": "NSE_FNO",
        "MCX": "MCX_COMM",
        "CDS": "NSE_CURRENCY",
    }
    INSTRUMENT_TYPE_MAP: dict[str, str] = {
        "NSE": "EQUITY",
        "BSE": "EQUITY",
        "NFO": "FUTIDX",
        "MCX": "FUTCOM",
        "CDS": "FUTCUR",
    }
    INTERVAL_MAP: dict[str, int] = {
        "1minute": 1,
        "5minute": 5,
        "15minute": 15,
        "30minute": 25,   # Dhan offers 25m, closest to 30m
        "60minute": 60,
    }

    def __init__(self):
        self.client_id = os.environ.get("DHAN_CLIENT_ID", "")
        self.token = os.environ.get("DHAN_ACCESS_TOKEN", "")
        self.client = None
        self.logged_in = False
        self._scrip_cache: dict[str, str] = {}  # EXCHANGE:SYMBOL → security_id
        self._scrip_cache_date: str | None = None

    def login(self) -> bool:
        # Try auto-token-refresh first (TOTP + PIN), then fall back to
        # static env token. This means Dhan tokens rotate automatically
        # at startup — no manual /dhantoken paste needed.
        token = self.token
        client_id = self.client_id

        if os.environ.get("DHAN_TOTP_KEY") and os.environ.get("DHAN_PIN"):
            try:
                from mcp_server.dhan_auth import get_dhan_token
                token = get_dhan_token()
                # Extract client_id from the JWT if not set explicitly.
                if not client_id:
                    import base64
                    payload = json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "=="))
                    client_id = str(payload.get("dhanClientId", ""))
                logger.info("Dhan token acquired via auto-refresh")
            except Exception as auth_err:
                logger.warning("Dhan auto-refresh failed: %s — trying static token", auth_err)

        if not client_id or not token:
            logger.warning("DHAN_CLIENT_ID or DHAN_ACCESS_TOKEN not set — skipping Dhan")
            return False
        try:
            from dhanhq import DhanContext, dhanhq
            self.client = dhanhq(DhanContext(client_id, token))
            self.logged_in = True
            logger.info("Dhan login OK")
            return True
        except ImportError:
            logger.warning("dhanhq not installed: pip install dhanhq")
        except Exception as e:
            logger.warning("Dhan login error: %s", e)
        return False

    # ── Instrument resolution ──────────────────────────────────

    def _load_scrip_master(self) -> None:
        """Load Dhan's instrument CSV (daily cache) to resolve ticker → security_id."""
        today = str(date.today())
        if self._scrip_cache_date == today and self._scrip_cache:
            return

        cache_path = Path("data/dhan_instruments.json")
        if cache_path.exists():
            try:
                cached = json.loads(cache_path.read_text())
                if cached.get("date") == today:
                    self._scrip_cache = cached.get("map", {})
                    self._scrip_cache_date = today
                    logger.info("Dhan scrip master from cache: %d symbols", len(self._scrip_cache))
                    return
            except Exception:
                pass

        try:
            csv_url = "https://images.dhan.co/api-data/api-scrip-master.csv"
            df = pd.read_csv(csv_url, low_memory=False)
            scrip_map: dict[str, str] = {}
            # For futures (MCX/NFO/CDS), build base-symbol → nearest-expiry
            # aliases so "MCX:GOLD" resolves to the current-month FUTCOM contract.
            # Track: (exchange, base_name) → (expiry_str, security_id)
            futures_best: dict[tuple[str, str], tuple[str, str]] = {}
            today_str = str(date.today())

            for _, row in df.iterrows():
                seg = str(row.get("SEM_EXM_EXCH_ID", "")).strip()
                symbol = str(row.get("SEM_TRADING_SYMBOL", "")).strip().upper()
                sec_id = str(row.get("SEM_SMST_SECURITY_ID", "")).strip()
                instr = str(row.get("SEM_INSTRUMENT_NAME", "")).strip().upper()
                expiry_raw = str(row.get("SEM_EXPIRY_DATE", "")).strip()
                if not seg or not symbol or not sec_id:
                    continue
                exchange_map_inv = {"NSE": "NSE", "BSE": "BSE", "MCX": "MCX"}
                exch = exchange_map_inv.get(seg)
                if not exch:
                    continue

                # Direct symbol mapping (equity, indices)
                scrip_map[f"{exch}:{symbol}"] = sec_id

                # Futures alias: pick nearest non-expired contract per base name.
                # MCX: FUTCOM/FUTIDX; NSE: FUTIDX/FUTSTK/FUTCUR
                if instr in ("FUTCOM", "FUTIDX", "FUTSTK", "FUTCUR"):
                    base = symbol.split("-")[0]
                    if not base:
                        continue
                    if expiry_raw < today_str:
                        continue
                    bkey = (exch, base)
                    existing = futures_best.get(bkey)
                    if existing is None or expiry_raw < existing[0]:
                        futures_best[bkey] = (expiry_raw, sec_id)

            # Apply futures aliases: MCX:GOLD → nearest FUTCOM security_id
            for (exch, base), (_, sec_id) in futures_best.items():
                alias_key = f"{exch}:{base}"
                if alias_key not in scrip_map or exch != "NSE":
                    scrip_map[alias_key] = sec_id

            # Also map NFO base names for index futures
            for (exch, base), (_, sec_id) in futures_best.items():
                if exch == "NSE" and base in ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"):
                    scrip_map[f"NFO:{base}"] = sec_id
                elif exch == "NSE":
                    # CDS currency futures
                    if base in ("USDINR", "EURINR", "GBPINR", "JPYINR"):
                        scrip_map[f"CDS:{base}"] = sec_id

            if scrip_map:
                self._scrip_cache = scrip_map
                self._scrip_cache_date = today
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(json.dumps({"date": today, "map": scrip_map}))
                futures_count = len(futures_best)
                logger.info(
                    "Dhan scrip master downloaded: %d symbols (%d futures aliases)",
                    len(scrip_map), futures_count,
                )
        except Exception as e:
            logger.warning("Dhan scrip master load failed: %s", e)

    def _resolve_security_id(self, symbol: str, exchange: str = "NSE") -> str | None:
        """Resolve SYMBOL → Dhan security_id string."""
        self._load_scrip_master()
        return self._scrip_cache.get(f"{exchange}:{symbol.upper()}")

    # ── Historical data ────────────────────────────────────────

    @retry(max_attempts=2, delay=1.0)
    def get_historical(self, symbol: str,
                       interval: str = "day",
                       days: int = 60,
                       exchange: str = "NSE") -> pd.DataFrame:
        if not self.logged_in:
            return pd.DataFrame()

        sec_id = self._resolve_security_id(symbol, exchange)
        if not sec_id:
            logger.debug("Dhan: no security_id for %s:%s", exchange, symbol)
            return pd.DataFrame()

        dhan_segment = self.EXCHANGE_MAP.get(exchange, "NSE_EQ")
        instr_type = self.INSTRUMENT_TYPE_MAP.get(exchange, "EQUITY")
        from_date = (date.today() - timedelta(days=days)).strftime("%Y-%m-%d")
        to_date = date.today().strftime("%Y-%m-%d")

        try:
            if interval == "day":
                resp = self.client.historical_daily_data(
                    security_id=sec_id,
                    exchange_segment=dhan_segment,
                    instrument_type=instr_type,
                    from_date=from_date,
                    to_date=to_date,
                )
            else:
                dhan_interval = self.INTERVAL_MAP.get(interval)
                if dhan_interval is None:
                    logger.debug("Dhan: unsupported interval %s", interval)
                    return pd.DataFrame()
                from_dt = (date.today() - timedelta(days=days)).strftime("%Y-%m-%d 09:15:00")
                to_dt = date.today().strftime("%Y-%m-%d 15:30:00")
                resp = self.client.intraday_minute_data(
                    security_id=sec_id,
                    exchange_segment=dhan_segment,
                    instrument_type=instr_type,
                    from_date=from_dt,
                    to_date=to_dt,
                    interval=dhan_interval,
                )

            if resp and resp.get("data"):
                raw = resp["data"]
                # Dhan sometimes returns a single dict instead of a list
                # for symbols with only one data point. Guard against it
                # so pd.DataFrame doesn't raise "must pass an index".
                if isinstance(raw, dict):
                    raw = [raw]
                if not isinstance(raw, list) or not raw:
                    return pd.DataFrame()
                df = pd.DataFrame(raw)
                rename = {
                    "timestamp": "date", "start_Time": "date",
                    "open": "open", "high": "high",
                    "low": "low", "close": "close", "volume": "volume",
                }
                df = df.rename(columns={
                    k: v for k, v in rename.items() if k in df.columns
                })
                if "date" not in df.columns:
                    date_cols = [c for c in df.columns if "time" in c.lower() or "date" in c.lower()]
                    if date_cols:
                        df = df.rename(columns={date_cols[0]: "date"})
                df["date"] = pd.to_datetime(df["date"])
                needed = ["date", "open", "high", "low", "close", "volume"]
                avail = [c for c in needed if c in df.columns]
                if len(avail) >= 5:
                    return df[avail].sort_values("date").reset_index(drop=True)
        except Exception as e:
            logger.warning("Dhan historical failed for %s:%s (%s): %s", exchange, symbol, interval, e)
        return pd.DataFrame()

    # ── Live quote ─────────────────────────────────────────────

    # ── Option chain ─────────────────────────────────────────

    def get_expiry_list(self, symbol: str, exchange: str = "NSE") -> list[str]:
        """Return available expiry dates (YYYY-MM-DD strings) for an underlying."""
        if not self.logged_in:
            return []
        sec_id = self._resolve_security_id(symbol, exchange)
        if not sec_id:
            return []
        dhan_segment = self.EXCHANGE_MAP.get(exchange, "NSE_EQ")
        try:
            resp = self.client.expiry_list(
                under_security_id=sec_id,
                under_exchange_segment=dhan_segment,
            )
            if resp and resp.get("data"):
                return [str(d) for d in resp["data"]]
        except Exception as e:
            logger.debug("Dhan expiry_list failed for %s:%s: %s", exchange, symbol, e)
        return []

    def get_option_chain(self, symbol: str, expiry: str, exchange: str = "NSE") -> dict:
        """Fetch Dhan option chain and normalize to the Kite-compatible shape.

        Returns: {strike: {"CE": {oi, ltp, volume, iv, ...}, "PE": {...}}}
        so `options_selector` and `fo_module` can consume it interchangeably.
        """
        if not self.logged_in:
            return {}
        sec_id = self._resolve_security_id(symbol, exchange)
        if not sec_id:
            return {}
        dhan_segment = self.EXCHANGE_MAP.get(exchange, "NSE_EQ")
        try:
            resp = self.client.option_chain(
                under_security_id=sec_id,
                under_exchange_segment=dhan_segment,
                expiry=expiry,
            )
            if not resp or not resp.get("data"):
                return {}

            chain: dict[float, dict] = {}
            for row in resp["data"]:
                strike = float(row.get("strikePrice", 0))
                if strike <= 0:
                    continue
                opt_type = row.get("optionType", "").upper()
                if opt_type not in ("CE", "PE", "CALL", "PUT"):
                    continue
                opt_type = "CE" if opt_type in ("CE", "CALL") else "PE"

                if strike not in chain:
                    chain[strike] = {}
                chain[strike][opt_type] = {
                    "oi": int(row.get("oi", row.get("openInterest", 0))),
                    "ltp": float(row.get("ltp", row.get("lastTradedPrice", 0))),
                    "volume": int(row.get("volume", row.get("tradedVolume", 0))),
                    "iv": float(row.get("iv", row.get("impliedVolatility", 0))),
                    "delta": float(row.get("delta", 0)),
                    "gamma": float(row.get("gamma", 0)),
                    "theta": float(row.get("theta", 0)),
                    "vega": float(row.get("vega", 0)),
                    "tradingsymbol": str(row.get("tradingSymbol", row.get("scrip", ""))),
                    "token": str(row.get("securityId", row.get("security_id", ""))),
                }
            logger.info("Dhan option chain for %s exp %s: %d strikes", symbol, expiry, len(chain))
            return chain
        except Exception as e:
            logger.warning("Dhan option chain failed for %s:%s exp=%s: %s", exchange, symbol, expiry, e)
            return {}

    # ── Live quote ─────────────────────────────────────────

    @retry(max_attempts=2, delay=0.5)
    def get_quote(self, symbol: str, exchange: str = "NSE") -> dict:
        if not self.logged_in:
            return {}
        sec_id = self._resolve_security_id(symbol, exchange)
        if not sec_id:
            return {}
        dhan_segment = self.EXCHANGE_MAP.get(exchange, "NSE_EQ")
        try:
            resp = self.client.quote_data({dhan_segment: [sec_id]})
            if resp and resp.get("data"):
                entries = resp["data"]
                if isinstance(entries, dict):
                    entry = entries.get(sec_id, {})
                elif isinstance(entries, list) and entries:
                    entry = entries[0]
                else:
                    entry = {}
                ltp = float(entry.get("last_price", entry.get("ltp", 0)))
                if ltp:
                    return {
                        "symbol": symbol,
                        "exchange": exchange,
                        "source": "DHAN",
                        "ltp": ltp,
                        "open": float(entry.get("open", 0)),
                        "high": float(entry.get("high", 0)),
                        "low": float(entry.get("low", 0)),
                        "volume": int(entry.get("volume", 0)),
                    }
        except Exception as e:
            logger.debug("Dhan quote failed for %s:%s: %s", exchange, symbol, e)
        return {}


# ══════════════════════════════════════════════════════════════════
# MASTER DATA PROVIDER — Orchestrates all sources with failover
# ══════════════════════════════════════════════════════════════════

class MarketDataProvider:
    """
    Multi-source Indian market data provider with automatic failover.

    Usage:
        provider = MarketDataProvider()
        provider.initialise()
        df = provider.get_ohlcv("RELIANCE", interval="day", days=60)
        quote = provider.get_quote("RELIANCE")
    """

    def __init__(self):
        self.nse = NSESource()
        self.gwc = GoodwillSource()
        self.angel = AngelSource()
        self.upstox = UpstoxSource()
        self.dhan = DhanSource()

        self._sources = {
            "nse": True,     # Always available — no key needed
            "gwc": False,
            "angel": False,
            "upstox": False,
            "dhan": False,
        }

        # Quote cache (symbol → {quote, timestamp})
        self._quote_cache: Dict[str, dict] = {}
        self._cache_ttl = 15  # seconds

        # Historical cache (symbol+interval → DataFrame)
        self._hist_cache: Dict[str, tuple] = {}
        self._hist_ttl = 3600  # 1 hour

    def initialise(self, sources: list = None):
        """Login to all available sources."""
        to_try = sources or ["gwc", "angel", "upstox", "dhan"]

        if "gwc" in to_try:
            self._sources["gwc"] = self.gwc.login()
        if "angel" in to_try:
            self._sources["angel"] = self.angel.login()
        if "upstox" in to_try:
            self._sources["upstox"] = self.upstox.login()
        if "dhan" in to_try:
            self._sources["dhan"] = self.dhan.login()

        for src, ok in self._sources.items():
            logger.info("  %s: %s", src, "available" if ok else "not available")

        available = sum(1 for ok in self._sources.values() if ok)
        logger.info("MarketDataProvider: %d sources available (NSE India always on)", available + 1)
        return self

    # ── OHLCV Historical ─────────────────────────────────────────

    def get_ohlcv(self, symbol: str,
                  interval: str = "day",
                  days: int = 60,
                  exchange: str = "NSE") -> pd.DataFrame:
        """
        Get OHLCV candle data from best available source.
        Priority: Angel → NSE India → Upstox → Dhan
        """
        cache_key = f"{symbol}_{interval}_{days}_{exchange}"
        if cache_key in self._hist_cache:
            df, ts = self._hist_cache[cache_key]
            if (time.time() - ts) < self._hist_ttl and not df.empty:
                return df

        symbol_clean = symbol.replace("NSE:", "").replace("BSE:", "")

        # 1. Angel SmartAPI (supports all segments: NSE/BSE/NFO/MCX/CDS/BFO)
        # Routed through _angel_fetch_with_refresh so the session-level
        # circuit breaker (trips on AG8001 after refresh retry) applies.
        if self._sources["angel"] and not self.angel.is_disabled():
            df = self._angel_fetch_with_refresh(symbol_clean, interval, days, exchange)
            if not df.empty:
                self._hist_cache[cache_key] = (df, time.time())
                return df
            logger.warning("Angel OHLCV failed for %s, trying NSE...", symbol_clean)

        # 2. NSE India free (equity only)
        if exchange in ("NSE", "BSE"):
            try:
                from_dt = (now_ist() - timedelta(days=days)).strftime("%d-%m-%Y")
                to_dt = now_ist().strftime("%d-%m-%Y")
                df = self.nse.get_historical(symbol_clean, from_dt, to_dt)
                if not df.empty:
                    self._hist_cache[cache_key] = (df, time.time())
                    return df
            except Exception as e:
                logger.warning("NSE historical failed for %s: %s", symbol_clean, e)

        # 3. Upstox (equity only)
        if self._sources["upstox"] and exchange in ("NSE", "BSE"):
            df = self.upstox.get_historical(symbol_clean, interval, days)
            if not df.empty:
                self._hist_cache[cache_key] = (df, time.time())
                return df

        # 4. Dhan (all segments + intraday)
        if self._sources["dhan"]:
            df = self.dhan.get_historical(symbol_clean, interval, days, exchange=exchange)
            if not df.empty:
                self._hist_cache[cache_key] = (df, time.time())
                return df

        logger.error("All historical sources failed for %s", symbol_clean)
        return pd.DataFrame()

    # ── Segment-Routed OHLCV ───────────────────────────────────

    def get_ohlcv_routed(
        self,
        symbol: str,
        interval: str = "day",
        days: int = 60,
        exchange: str = "NSE",
    ) -> pd.DataFrame:
        """Get OHLCV from best source for the given exchange/segment.

        Uses SEGMENT_ROUTING to determine source priority per exchange.
        Falls back gracefully when a source isn't configured.
        """
        cache_key = f"routed_{symbol}_{interval}_{days}_{exchange}"
        if cache_key in self._hist_cache:
            df, ts = self._hist_cache[cache_key]
            if (time.time() - ts) < self._hist_ttl and not df.empty:
                return df

        symbol_clean = symbol.replace("NSE:", "").replace("BSE:", "").replace("MCX:", "").replace("CDS:", "").replace("NFO:", "")
        sources = SEGMENT_ROUTING.get(exchange, ["yfinance"])

        for source in sources:
            df = self._try_source_ohlcv(source, symbol_clean, interval, days, exchange)
            if df is not None and not df.empty:
                logger.info("Routed %s:%s via %s (%d bars)", exchange, symbol_clean, source, len(df))
                self._hist_cache[cache_key] = (df, time.time())
                return df

        logger.warning("All routed sources failed for %s:%s (tried %s)", exchange, symbol_clean, sources)
        return pd.DataFrame()

    def _try_source_ohlcv(
        self,
        source: str,
        symbol: str,
        interval: str,
        days: int,
        exchange: str,
    ) -> pd.DataFrame:
        """Try a single data source for OHLCV. Returns empty DF on failure."""
        try:
            if source == "angel" and self._sources.get("angel") and not self.angel.is_disabled():
                return self._angel_fetch_with_refresh(symbol, interval, days, exchange)
            elif source == "nse" and exchange in ("NSE", "BSE"):
                from_dt = (now_ist() - timedelta(days=days)).strftime("%d-%m-%Y")
                to_dt = now_ist().strftime("%d-%m-%Y")
                return self.nse.get_historical(symbol, from_dt, to_dt)
            elif source == "gwc" and self._sources.get("gwc"):
                # Goodwill quote only — no historical OHLCV endpoint currently
                return pd.DataFrame()
            elif source == "kite":
                try:
                    from mcp_server.kite_auth import get_authenticated_kite
                    kite = get_authenticated_kite()
                    from mcp_server.data_provider import _resolve_instrument_token, _INTERVAL_MAP
                    token = _resolve_instrument_token(f"{exchange}:{symbol}")
                    if token is None:
                        return pd.DataFrame()
                    kite_interval = _INTERVAL_MAP.get(
                        {"day": "1d", "1minute": "1m", "5minute": "5m",
                         "15minute": "15m", "60minute": "1h"}.get(interval, "1d"),
                        "day",
                    )
                    to_date = now_ist()
                    from_date = to_date - timedelta(days=days)
                    records = kite.historical_data(
                        instrument_token=token,
                        from_date=from_date,
                        to_date=to_date,
                        interval=kite_interval,
                    )
                    if records:
                        df = pd.DataFrame(records)
                        df["date"] = pd.to_datetime(df["date"])
                        return df[["date", "open", "high", "low", "close", "volume"]].sort_values("date").reset_index(drop=True)
                except Exception as e:
                    logger.debug("Kite source failed for %s:%s: %s", exchange, symbol, e)
                return pd.DataFrame()
            elif source == "dhan" and self._sources.get("dhan"):
                return self.dhan.get_historical(symbol, interval, days, exchange=exchange)
            elif source == "upstox" and self._sources.get("upstox") and exchange in ("NSE", "BSE"):
                return self.upstox.get_historical(symbol, interval, days)
            elif source == "yfinance":
                ticker_str = f"{exchange}:{symbol}" if exchange not in ("NSE", "BSE") else symbol
                yf_symbol = resolve_yf_symbol(ticker_str)
                if not yf_symbol:
                    return pd.DataFrame()
                # Futures (=F) and FX pairs (=X) return only 1 bar when called
                # with period strings — use explicit start/end dates instead.
                if _is_futures_or_fx_symbol(yf_symbol):
                    start_dt = (date.today() - timedelta(days=days + 5)).isoformat()
                    end_dt = (date.today() + timedelta(days=1)).isoformat()
                    data = _rate_limited_download(
                        yf_symbol, start=start_dt, end=end_dt, interval="1d",
                    )
                else:
                    period_map = {1: "1d", 5: "5d", 30: "1mo", 60: "3mo", 90: "3mo",
                                  180: "6mo", 365: "1y", 730: "2y"}
                    period = "6mo"
                    for d, p in sorted(period_map.items()):
                        if days <= d:
                            period = p
                            break
                    data = _rate_limited_download(yf_symbol, period=period, interval="1d")
                if not data.empty:
                    data.columns = [
                        c.lower() if isinstance(c, str) else c[0].lower()
                        for c in data.columns
                    ]
                    if isinstance(data.columns, pd.MultiIndex):
                        data.columns = data.columns.get_level_values(0)
                        data.columns = [c.lower() for c in data.columns]
                    required = ["open", "high", "low", "close", "volume"]
                    if all(c in data.columns for c in required):
                        data = data[required].copy()
                        data.index.name = "date"
                        return data.reset_index()
                return pd.DataFrame()
        except Exception as e:
            logger.debug("Source %s failed for %s:%s: %s", source, exchange, symbol, e)
        return pd.DataFrame()

    def _angel_fetch_with_refresh(
        self,
        symbol: str,
        interval: str,
        days: int,
        exchange: str,
    ) -> pd.DataFrame:
        """Fetch OHLCV from Angel with auto-refresh on Invalid Token.

        Circuit breaker: once a force-refresh retry still returns AG8001
        (i.e. the token is valid but Angel's IP whitelist rejects us),
        we trip the sticky session breaker so subsequent tickers skip
        Angel entirely for the rest of the session. This prevents the
        scan from doing N × (3s TOTP login + AG8001 retry) on every
        ticker when the server IP isn't whitelisted.
        """
        # Fast path: session breaker already tripped → skip without any call.
        if self.angel.is_disabled():
            return pd.DataFrame()
        try:
            df = self.angel.get_historical(symbol, interval, days, exchange=exchange)
            if not df.empty:
                return df
            # Empty df without exception = searchScrip/getCandleData returned
            # a silent failure (common with AG8001 on older SDK versions that
            # log the error but don't raise). Fall through to the refresh +
            # retry path so the sticky breaker has a chance to trip.
            logger.warning(
                "Angel returned empty df for %s:%s — attempting force refresh",
                exchange, symbol,
            )
        except AngelTokenInvalid as token_err:
            logger.warning(
                "Angel token expired for %s:%s (%s) — attempting force refresh",
                exchange, symbol, token_err,
            )
        except Exception as e:
            if _is_angel_token_error(str(e)):
                logger.warning(
                    "Angel token expired for %s:%s (%s) — attempting force refresh",
                    exchange, symbol, e,
                )
            else:
                logger.debug("Angel fetch failed for %s:%s: %s", exchange, symbol, e)
                return pd.DataFrame()
        # If the breaker was already tripped by get_historical→_get_token
        # while we were in the try block, skip the refresh attempt.
        if self.angel.is_disabled():
            return pd.DataFrame()

        # Force-refresh the JWT and retry once. Clear the symbol→token cache
        # because tokens are tied to the old session.
        try:
            from mcp_server.angel_auth import force_refresh_angel_token
            self.angel.client = force_refresh_angel_token()
            self.angel.logged_in = True
            self.angel._token_cache.clear()
            self._sources["angel"] = True
        except Exception as refresh_err:
            logger.error(
                "Angel token refresh failed: %s — tripping session breaker",
                refresh_err,
            )
            self.angel.trip_breaker(f"force_refresh_angel_token failed: {refresh_err}")
            self._sources["angel"] = False
            return pd.DataFrame()

        try:
            df = self.angel.get_historical(symbol, interval, days, exchange=exchange)
            if not df.empty:
                logger.info(
                    "Angel token refreshed — retry succeeded for %s:%s",
                    exchange, symbol,
                )
                return df
            # Empty df after refresh → likely IP whitelist issue. Trip breaker.
            logger.error(
                "Angel retry returned empty for %s:%s after fresh TOTP login — "
                "tripping session breaker (likely IP whitelist issue)",
                exchange, symbol,
            )
            self.angel.trip_breaker(
                f"empty df after refresh for {exchange}:{symbol}"
            )
            self._sources["angel"] = False
        except AngelTokenInvalid as retry_err:
            logger.error(
                "Angel retry after refresh still AG8001 for %s:%s (%s) — "
                "tripping session breaker (likely IP whitelist issue)",
                exchange, symbol, retry_err,
            )
            self.angel.trip_breaker(f"AG8001 after refresh: {retry_err}")
            self._sources["angel"] = False
        except Exception as retry_err:
            logger.error(
                "Angel retry after refresh failed for %s:%s: %s — "
                "tripping session breaker",
                exchange, symbol, retry_err,
            )
            self.angel.trip_breaker(f"retry exception: {retry_err}")
            self._sources["angel"] = False
        return pd.DataFrame()

    # ── Live Quote ───────────────────────────────────────────────

    def get_quote(self, symbol: str, exchange: str = "NSE") -> dict:
        """Live quote. Priority: Angel → Goodwill → NSE India."""
        symbol_clean = symbol.replace("NSE:", "").replace("BSE:", "")

        cache_key = f"quote_{symbol_clean}_{exchange}"
        if cache_key in self._quote_cache:
            q, ts = self._quote_cache[cache_key]
            if (time.time() - ts) < self._cache_ttl:
                return q

        quote = {}

        # 1. Angel SmartAPI (supports all segments). Trips the sticky session
        # circuit breaker on AG8001 so every subsequent quote skips Angel.
        if self._sources["angel"] and not self.angel.is_disabled():
            try:
                quote = self.angel.get_quote(symbol_clean, exchange=exchange)
            except AngelTokenInvalid as ag_err:
                logger.warning(
                    "Angel quote AG8001 for %s:%s (%s) — tripping session breaker",
                    exchange, symbol_clean, ag_err,
                )
                self.angel.trip_breaker(f"quote AG8001: {ag_err}")
                self._sources["angel"] = False
            except Exception as quote_err:
                if _is_angel_token_error(str(quote_err)):
                    logger.warning(
                        "Angel quote AG8001 for %s:%s — tripping session breaker",
                        exchange, symbol_clean,
                    )
                    self.angel.trip_breaker(f"quote AG8001: {quote_err}")
                    self._sources["angel"] = False

        # 2. Goodwill
        if not quote.get("ltp") and self._sources["gwc"]:
            try:
                quote = self.gwc.get_quote(exchange, symbol_clean)
            except Exception:
                pass

        # 3. NSE India (equity only)
        if not quote.get("ltp") and exchange in ("NSE", "BSE"):
            try:
                quote = self.nse.get_quote(symbol_clean)
            except Exception:
                pass

        if quote:
            self._quote_cache[cache_key] = (quote, time.time())
        return quote

    def get_ltp(self, symbol: str) -> float:
        exchange = "NSE"
        symbol_clean = symbol
        if ":" in symbol:
            exchange, symbol_clean = symbol.split(":", 1)
        return self.get_quote(symbol_clean, exchange=exchange).get("ltp", 0.0)

    # ── India-Specific Data (NSE only) ───────────────────────────

    def get_fii_dii(self) -> dict:
        return self.nse.get_fii_dii()

    def get_delivery_pct(self, symbol: str) -> dict:
        return self.nse.get_delivery_pct(symbol.replace("NSE:", ""))

    def get_pcr(self, symbol: str = "NIFTY") -> dict:
        return self.nse.get_pcr(symbol)

    def get_option_chain(self, symbol: str = "NIFTY") -> dict:
        return self.nse.get_option_chain(symbol)

    def get_52week_stocks(self) -> dict:
        return self.nse.get_52week_stocks()

    def get_bulk_deals(self) -> list:
        return self.nse.get_bulk_deals()

    # ── Trading (Goodwill) ───────────────────────────────────────

    def place_order(self, symbol: str, action: str, qty: int,
                    price: float = 0, order_type: str = "MKT",
                    product: str = "MIS", exchange: str = "NSE") -> dict:
        if not self._sources["gwc"]:
            return {"status": "error", "message": "Goodwill not available"}
        return self.gwc.place_order(exchange, symbol, action, qty,
                                    price, order_type, product)

    def get_positions(self) -> list:
        return self.gwc.get_positions() if self._sources["gwc"] else []

    def get_holdings(self) -> list:
        return self.gwc.get_holdings() if self._sources["gwc"] else []

    def get_balance(self) -> dict:
        return self.gwc.get_balance() if self._sources["gwc"] else {}

    def get_orders(self) -> list:
        return self.gwc.get_orders() if self._sources["gwc"] else []

    # ── Morning Pipeline Data ────────────────────────────────────

    def get_morning_data(self, watchlist: list) -> dict:
        """Fetch all data needed for morning pipeline in one call."""
        logger.info("Fetching morning data for %d stocks...", len(watchlist))

        fii_dii = self.get_fii_dii()
        nifty_pcr = self.get_pcr("NIFTY")
        bn_pcr = self.get_pcr("BANKNIFTY")
        week52 = self.get_52week_stocks()
        bulk_deals = self.get_bulk_deals()

        quotes = {}
        delivery = {}
        for sym in watchlist:
            clean = sym.replace("NSE:", "")
            try:
                quotes[sym] = self.get_quote(clean)
                delivery[sym] = self.get_delivery_pct(clean)
                time.sleep(0.1)
            except Exception as e:
                logger.warning("Morning data failed for %s: %s", sym, e)

        return {
            "timestamp": now_ist().isoformat(),
            "fii_dii": fii_dii,
            "nifty_pcr": nifty_pcr,
            "bn_pcr": bn_pcr,
            "52w_highs": week52.get("52w_highs", []),
            "52w_lows": week52.get("52w_lows", []),
            "bulk_deals": bulk_deals,
            "quotes": quotes,
            "delivery": delivery,
            "fii_buying": fii_dii.get("fii_buying", True),
            "market_open": 9 <= now_ist().hour < 16,
        }

    # ── Diagnostics ──────────────────────────────────────────────

    def status(self) -> dict:
        return {
            "sources": self._sources,
            "quote_cache": len(self._quote_cache),
            "hist_cache": len(self._hist_cache),
            "primary_quote": "goodwill" if self._sources["gwc"] else "nse",
            "primary_history": "angel" if self._sources["angel"] else "nse",
        }


# ══════════════════════════════════════════════════════════════════
# SINGLETON INSTANCE
# ══════════════════════════════════════════════════════════════════

_provider_instance: Optional[MarketDataProvider] = None


def get_provider() -> MarketDataProvider:
    """Get or create the global MarketDataProvider instance."""
    global _provider_instance
    if _provider_instance is None:
        _provider_instance = MarketDataProvider()
        _provider_instance.initialise()
    return _provider_instance


# ══════════════════════════════════════════════════════════════════
# BACKWARD-COMPATIBLE FUNCTIONS
# These maintain the exact same signatures used throughout the codebase.
# ══════════════════════════════════════════════════════════════════

# ── Kite Instrument Token Cache (kept for backward compat) ────────

_instrument_cache: dict[str, int] = {}
_cache_loaded_date: str | None = None
_kite_failed_today: str | None = None  # Cache Kite auth failures to prevent retry storm


def _load_instrument_cache() -> None:
    """Load instrument tokens from Kite (used if Kite fallback is needed)."""
    global _instrument_cache, _cache_loaded_date, _kite_failed_today

    today = str(date.today())

    # Already loaded successfully today
    if _cache_loaded_date == today and _instrument_cache:
        return

    # Kite auth already failed today — don't retry (prevents TOTP storm)
    if _kite_failed_today == today:
        return

    try:
        from mcp_server.kite_auth import get_authenticated_kite
        kite = get_authenticated_kite()

        _instrument_cache.clear()

        # Secondary index: for MCX/NFO/CDS we also want to resolve *base*
        # symbols (e.g. "CRUDEOIL") to the nearest-expiry *futures* token.
        # Kite's instruments dump keys by full tradingsymbol
        # ("CRUDEOIL26APRFUT"), so a plain "MCX:CRUDEOIL" lookup would miss.
        # Without this alias, MCX/CDS scanners fall through to yfinance and
        # pick up NYMEX/COMEX proxies instead of real MCX FUTCOM prices.
        # Map: (exchange, base_name) -> (expiry_date, instrument_token)
        base_symbol_best: dict[tuple[str, str], tuple[date, int]] = {}
        today_d = date.today()

        def _inst_expiry_date(inst: dict) -> date | None:
            exp = inst.get("expiry")
            if exp is None or exp == "":
                return None
            if isinstance(exp, date):
                return exp
            if hasattr(exp, "date"):
                try:
                    return exp.date()
                except Exception:
                    return None
            try:
                return datetime.strptime(str(exp), "%Y-%m-%d").date()
            except Exception:
                return None

        for exch in ["NSE", "BSE", "MCX", "CDS", "NFO"]:
            try:
                instruments = kite.instruments(exch)
                fut_count = 0
                for inst in instruments:
                    key = f"{exch}:{inst['tradingsymbol']}"
                    _instrument_cache[key] = inst["instrument_token"]

                    # Only build base-symbol aliases for derivatives futures
                    # (MCX FUTCOM, NFO FUTSTK/FUTIDX, CDS FUTCUR).
                    if exch not in ("MCX", "NFO", "CDS"):
                        continue
                    itype = inst.get("instrument_type", "")
                    if itype != "FUT":
                        continue  # skip CE/PE options
                    base = (inst.get("name") or "").strip()
                    if not base:
                        continue
                    exp_d = _inst_expiry_date(inst)
                    if exp_d is None or exp_d < today_d:
                        continue  # skip expired / undated
                    bkey = (exch, base.upper())
                    existing = base_symbol_best.get(bkey)
                    if existing is None or exp_d < existing[0]:
                        base_symbol_best[bkey] = (exp_d, inst["instrument_token"])
                        fut_count += 1
                logger.info(
                    "Loaded %d instruments for %s (futures aliases so far: %d)",
                    len(instruments), exch, fut_count if exch in ("MCX", "NFO", "CDS") else 0,
                )
            except Exception as e:
                logger.warning("Failed to load instruments for %s: %s", exch, e)

        # Alias each base symbol to its nearest-expiry futures token so
        # "MCX:CRUDEOIL" resolves to "CRUDEOIL<nearest>FUT" transparently.
        for (exch, base), (_exp, token) in base_symbol_best.items():
            _instrument_cache[f"{exch}:{base}"] = token
        logger.info(
            "Kite base-symbol aliases: %d (MCX/NFO/CDS nearest-expiry futures)",
            len(base_symbol_best),
        )

        _cache_loaded_date = today
        _kite_failed_today = None  # Clear failure flag on success
        logger.info("Instrument cache loaded: %d total tokens", len(_instrument_cache))
    except Exception as e:
        _kite_failed_today = today  # Cache failure — skip retries for rest of today
        logger.warning("Instrument cache load failed (Kite unavailable): %s — skipping Kite for today", e)


def _resolve_instrument_token(ticker: str) -> int | None:
    """Resolve EXCHANGE:SYMBOL to Kite instrument token."""
    _load_instrument_cache()
    exchange, symbol = parse_ticker(ticker)
    key = f"{exchange}:{symbol}"
    token = _instrument_cache.get(key)
    if token is not None:
        return token
    logger.debug("No instrument token for %s", key)
    return None


def reset_kite_failure_flag() -> None:
    """Clear the sticky "_kite_failed_today" flag so the next instrument
    cache load retries. Call this after a successful manual Kite login
    (handle_kite_callback) — otherwise a morning race between the scanner's
    TOTP flow and the user's /kitelogin flow leaves the process with a
    broken instrument cache for the rest of the day, and MCX/NFO/CDS
    resolution silently falls through to yfinance proxies (or, post-fix,
    returns empty DataFrames).
    """
    global _kite_failed_today, _cache_loaded_date
    _kite_failed_today = None
    _cache_loaded_date = None
    logger.info("Kite failure flag cleared — instrument cache will reload on next lookup")


def force_reload_instrument_cache() -> int:
    """Force an immediate reload of the Kite instrument cache. Returns
    the number of tokens loaded. Used by admin endpoints and by the
    manual-login callback path to prime the cache right after a fresh
    token becomes available.
    """
    global _cache_loaded_date, _kite_failed_today
    _cache_loaded_date = None
    _kite_failed_today = None
    _instrument_cache.clear()
    _load_instrument_cache()
    return len(_instrument_cache)


# ── yfinance Rate Limiter (kept as last-resort fallback) ─────────

_YF_MIN_DELAY = 0.5
_YF_MAX_RETRIES = 3
_YF_RETRY_BACKOFF = 2.0
_last_yf_request_time = 0.0


def _rate_limited_download(symbol: str, **kwargs) -> pd.DataFrame:
    """yfinance download with rate limiting and retry logic."""
    global _last_yf_request_time

    for attempt in range(_YF_MAX_RETRIES):
        elapsed = time.time() - _last_yf_request_time
        if elapsed < _YF_MIN_DELAY:
            time.sleep(_YF_MIN_DELAY - elapsed)

        try:
            _last_yf_request_time = time.time()
            data = yf.download(symbol, progress=False, **kwargs)
            if not data.empty:
                return data
            if attempt < _YF_MAX_RETRIES - 1:
                wait = _YF_RETRY_BACKOFF ** attempt
                logger.warning(
                    "Empty data for %s, retry %d/%d in %.1fs",
                    symbol, attempt + 1, _YF_MAX_RETRIES, wait,
                )
                time.sleep(wait)
        except Exception as e:
            if attempt < _YF_MAX_RETRIES - 1:
                wait = _YF_RETRY_BACKOFF ** attempt
                logger.warning(
                    "yfinance error for %s: %s — retry %d/%d in %.1fs",
                    symbol, e, attempt + 1, _YF_MAX_RETRIES, wait,
                )
                time.sleep(wait)
            else:
                logger.error(
                    "yfinance failed after %d retries for %s: %s",
                    _YF_MAX_RETRIES, symbol, e,
                )

    return pd.DataFrame()


# ── Kite Historical (kept as fallback for MCX/CDS/NFO) ───────────

def fetch_kite_historical(
    ticker: str,
    period: str = "1y",
    interval: str = "1d",
) -> pd.DataFrame:
    """Fetch OHLCV from Kite Connect API (fallback for non-NSE instruments)."""
    token = _resolve_instrument_token(ticker)
    if token is None:
        raise ValueError(f"No instrument token for {ticker}")

    kite_interval = _INTERVAL_MAP.get(interval)
    if kite_interval is None:
        raise ValueError(f"Unsupported interval: {interval}")

    days = _PERIOD_TO_DAYS.get(period)
    if days is None:
        raise ValueError(f"Unsupported period: {period}")

    to_date = now_ist()
    from_date = to_date - timedelta(days=days)

    from mcp_server.kite_auth import get_authenticated_kite
    kite = get_authenticated_kite()

    records = kite.historical_data(
        instrument_token=token,
        from_date=from_date,
        to_date=to_date,
        interval=kite_interval,
    )

    if not records:
        raise ValueError(f"Kite returned no data for {ticker}")

    df = pd.DataFrame(records)
    col_map = {"date": "date", "open": "open", "high": "high",
               "low": "low", "close": "close", "volume": "volume"}
    df.rename(columns={k: v for k, v in col_map.items() if k in df.columns}, inplace=True)

    if "date" in df.columns:
        df.set_index("date", inplace=True)

    required = ["open", "high", "low", "close", "volume"]
    for col in required:
        if col not in df.columns:
            raise ValueError(f"Missing column {col} in Kite data for {ticker}")

    logger.info("Kite: fetched %d bars for %s (%s, %s)", len(df), ticker, period, interval)
    return df[required]


# ── yfinance Fallback ────────────────────────────────────────────

def _is_futures_or_fx_symbol(yf_symbol: str) -> bool:
    """Return True if the yfinance symbol is a continuous futures/FX contract.

    yfinance returns only 1 bar for continuous futures (NG=F, GC=F, CL=F...)
    and FX pairs (USDINR=X) when called with period strings. Using explicit
    start/end dates works around this issue.
    """
    return yf_symbol.endswith("=F") or yf_symbol.endswith("=X")


def _period_to_days(period: str) -> int:
    """Convert yfinance-style period string to a calendar day count."""
    return _PERIOD_TO_DAYS.get(period, 365)


def _yfinance_fetch(
    ticker: str,
    period: str = "1y",
    interval: str = "1d",
) -> pd.DataFrame:
    """Fetch OHLCV via yfinance (last-resort fallback)."""
    yf_symbol = resolve_yf_symbol(ticker)
    if yf_symbol is None:
        logger.warning("No yfinance symbol for %s — use broker API instead", ticker)
        return pd.DataFrame()

    try:
        # Futures (=F) and FX pairs (=X) misbehave with period strings and
        # return only 1 bar — use explicit start/end dates instead.
        if _is_futures_or_fx_symbol(yf_symbol) and interval in ("1d", "1wk", "1mo"):
            days = _period_to_days(period)
            # Pad by 5 days to cover weekends/holidays so we still hit the
            # requested bar count.
            start_dt = (date.today() - timedelta(days=days + 5)).isoformat()
            end_dt = (date.today() + timedelta(days=1)).isoformat()
            data = _rate_limited_download(
                yf_symbol, start=start_dt, end=end_dt, interval=interval,
            )
        else:
            data = _rate_limited_download(yf_symbol, period=period, interval=interval)

        if data.empty:
            logger.warning("No data returned for %s (yf: %s)", ticker, yf_symbol)
            return pd.DataFrame()

        data.columns = [
            c.lower() if isinstance(c, str) else c[0].lower()
            for c in data.columns
        ]

        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)
            data.columns = [c.lower() for c in data.columns]

        required = ["open", "high", "low", "close", "volume"]
        for col in required:
            if col not in data.columns:
                logger.error("Missing column %s in data for %s", col, ticker)
                return pd.DataFrame()

        logger.info(
            "yfinance: fetched %d bars for %s (yf: %s, %s, %s)",
            len(data), ticker, yf_symbol, period, interval,
        )
        return data[required]

    except Exception as e:
        logger.error("Failed to fetch data for %s (yf: %s): %s", ticker, yf_symbol, e)
        return pd.DataFrame()


# ── Unified get_stock_data() — Main entry point ─────────────────

def get_stock_data(
    ticker: str,
    period: str = "1y",
    interval: str = "1d",
    force_refresh: bool = False,
    **kwargs,
) -> pd.DataFrame:
    """
    Fetch OHLCV data for any instrument.

    Strategy: Cache → Multi-source provider → Kite fallback → yfinance fallback.

    Supports multi-exchange tickers:
        NSE:RELIANCE, BSE:RELIANCE, MCX:GOLD, CDS:USDINR, NFO:NIFTY

    Args:
        ticker: Symbol with optional exchange prefix (EXCHANGE:SYMBOL)
        period: Data period (1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y)
        interval: Data interval (1m, 5m, 15m, 1h, 1d, 1wk, 1mo)
        force_refresh: Skip cache check and force API fetch (default False)

    Returns:
        DataFrame with open, high, low, close, volume columns (lowercase)
    """
    # Step 1: Check OHLCV cache (unless force_refresh)
    if not force_refresh and settings.OHLCV_CACHE_ENABLED:
        try:
            from mcp_server.ohlcv_cache import check_cache
            from mcp_server.db import SessionLocal

            cache_session = SessionLocal()
            try:
                cached_df = check_cache(ticker, period, interval, cache_session)
                if cached_df is not None and not cached_df.empty:
                    return cached_df
            finally:
                cache_session.close()
        except Exception as e:
            logger.debug("Cache check skipped: %s", e)

    # Step 2: Try multi-source provider (new — free sources first)
    days = _PERIOD_TO_DAYS.get(period, 365)
    exchange_part = ""
    symbol_clean = ticker
    if ":" in ticker:
        exchange_part, symbol_clean = ticker.split(":", 1)

    # Map interval from get_stock_data format to provider format
    _interval_to_provider = {
        "1m": "1minute", "3m": "3minute", "5m": "5minute",
        "10m": "10minute", "15m": "15minute", "30m": "30minute",
        "1h": "60minute", "1d": "day", "1wk": "day", "1mo": "day",
    }
    provider_interval = _interval_to_provider.get(interval, "day")

    # Use multi-source provider for all Angel-supported exchanges
    angel_exchanges = ("NSE", "BSE", "NFO", "MCX", "CDS", "BFO")
    if not exchange_part or exchange_part in angel_exchanges:
        try:
            provider = get_provider()
            df = provider.get_ohlcv(symbol_clean, interval=provider_interval,
                                    days=days, exchange=exchange_part or "NSE")
            if not df.empty:
                # Normalize: ensure index-based format matching old behavior
                if "date" in df.columns:
                    df.set_index("date", inplace=True)
                required = ["open", "high", "low", "close", "volume"]
                avail = [c for c in required if c in df.columns]
                if len(avail) == 5:
                    source = "multi-source"
                    _store_to_cache(ticker, interval, df[required], source)
                    return df[required]
        except Exception as e:
            logger.warning("Multi-source provider failed for %s: %s", ticker, e)

    # Step 3: Kite fallback (especially for MCX/CDS/NFO)
    primary = settings.DATA_PROVIDER_PRIMARY
    if primary == "kite" or exchange_part in ("MCX", "CDS", "NFO"):
        try:
            df = fetch_kite_historical(ticker, period=period, interval=interval)
            if not df.empty:
                _store_to_cache(ticker, interval, df, "kite")
                return df
        except Exception as e:
            logger.warning("Kite failed for %s: %s", ticker, e)

    # Step 4: yfinance last resort — DELIBERATELY BLOCKED FOR MCX.
    # resolve_yf_symbol() maps MCX:CRUDEOIL → CL=F (NYMEX WTI, USD/barrel),
    # MCX:GOLD → GC=F (COMEX, USD/oz), etc. These are global proxies, NOT
    # real MCX FUTCOM prices in INR. If broker sources failed, better to
    # return an empty DF and let the caller skip the signal than to emit
    # wrong numbers. Same logic applies to NFO options which yfinance
    # cannot represent at all.
    if exchange_part in ("MCX", "NFO"):
        logger.warning(
            "get_stock_data: all broker sources failed for %s — "
            "yfinance blocked for MCX/NFO (would return wrong proxy).",
            ticker,
        )
        return pd.DataFrame()

    df = _yfinance_fetch(ticker, period=period, interval=interval)
    if not df.empty:
        _store_to_cache(ticker, interval, df, "yfinance")
    return df


def _store_to_cache(ticker: str, interval: str, df: pd.DataFrame, source: str) -> None:
    """Non-fatal cache store — logs warning on failure."""
    if not settings.OHLCV_CACHE_ENABLED:
        return
    try:
        from mcp_server.ohlcv_cache import store_cache
        from mcp_server.db import SessionLocal

        cache_session = SessionLocal()
        try:
            store_cache(ticker, interval, df, source, cache_session)
        finally:
            cache_session.close()
    except Exception as e:
        logger.warning("Cache store failed for %s: %s", ticker, e)
