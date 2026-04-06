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
import pyotp
import yfinance as yf
from datetime import datetime, timedelta, date
from pathlib import Path
from typing import Optional, Dict
from functools import wraps

from mcp_server.asset_registry import parse_ticker, resolve_yf_symbol
from mcp_server.config import settings

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


# ── Retry Decorator ──────────────────────────────────────────────

def retry(max_attempts: int = 3, delay: float = 1.0):
    """Retry decorator with exponential backoff."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
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
        if not self.api_key:
            logger.warning("GWC_API_KEY not set — skipping Goodwill login")
            return False
        try:
            totp = pyotp.TOTP(os.environ["GOODWILL_TOTP_KEY"]).now()
            resp = requests.post(f"{self.BASE}/login", json={
                "client_id": self.client_id,
                "password": os.environ.get("GOODWILL_PASSWORD", ""),
                "totp": totp,
            }, headers={"x-api-key": self.api_key}, timeout=10)
            data = resp.json()
            if data.get("status") == "success":
                self.access_token = data["data"]["access_token"]
                self.logged_in = True
                logger.info("Goodwill login OK")
                return True
            logger.warning("Goodwill login failed: %s", data.get("error_msg"))
        except Exception as e:
            logger.warning("Goodwill login error: %s", e)
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
        """Get instrument token for symbol (cached)."""
        key = f"{exchange}:{symbol}"
        if key in self._token_cache:
            return self._token_cache[key]
        try:
            data = self.client.searchScrip(exchange, symbol)
            if data and data.get("data"):
                token = data["data"][0]["symboltoken"]
                self._token_cache[key] = token
                return token
        except Exception:
            pass
        return None

    @retry(max_attempts=3, delay=1.0)
    def get_historical(self, symbol: str,
                       interval: str = "day",
                       days: int = 60,
                       exchange: str = "NSE") -> pd.DataFrame:
        """Historical OHLCV — best free source."""
        if not self.logged_in:
            return pd.DataFrame()

        token = self._get_token(symbol, exchange)
        if not token:
            logger.warning("Angel: no token found for %s", symbol)
            return pd.DataFrame()

        from_dt = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M")
        to_dt = datetime.now().strftime("%Y-%m-%d %H:%M")

        data = self.client.getCandleData({
            "exchange": exchange,
            "symboltoken": token,
            "interval": self.INTERVAL_MAP.get(interval, "ONE_DAY"),
            "fromdate": from_dt,
            "todate": to_dt,
        })

        if not data or not data.get("data"):
            return pd.DataFrame()

        df = pd.DataFrame(data["data"],
                          columns=["date", "open", "high", "low", "close", "volume"])
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
        return df

    @retry(max_attempts=2, delay=1.0)
    def get_quote(self, symbol: str, exchange: str = "NSE") -> dict:
        if not self.logged_in:
            return {}
        try:
            data = self.client.ltpData(exchange, symbol, self._get_token(symbol, exchange))
            ltp = data["data"]["ltp"] if data else 0
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

    def __init__(self):
        self.client_id = os.environ.get("DHAN_CLIENT_ID", "")
        self.token = os.environ.get("DHAN_ACCESS_TOKEN", "")
        self.client = None
        self.logged_in = False

    def login(self) -> bool:
        if not self.client_id or not self.token:
            logger.warning("DHAN_CLIENT_ID or DHAN_ACCESS_TOKEN not set — skipping Dhan")
            return False
        try:
            from dhanhq import dhanhq
            self.client = dhanhq(self.client_id, self.token)
            self.logged_in = True
            logger.info("Dhan login OK")
            return True
        except ImportError:
            logger.warning("dhanhq not installed: pip install dhanhq")
        except Exception as e:
            logger.warning("Dhan login error: %s", e)
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
            resp = self.client.historical_daily_data(
                symbol=symbol,
                exchange_segment=self.client.NSE,
                instrument_type="EQUITY",
                from_date=from_date,
                to_date=to_date,
            )
            if resp and resp.get("data"):
                df = pd.DataFrame(resp["data"])
                df = df.rename(columns={
                    "timestamp": "date",
                })
                df["date"] = pd.to_datetime(df["date"])
                return df[["date", "open", "high", "low", "close", "volume"]] \
                         .sort_values("date").reset_index(drop=True)
        except Exception as e:
            logger.warning("Dhan historical failed for %s: %s", symbol, e)
        return pd.DataFrame()


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
        if self._sources["angel"]:
            df = self.angel.get_historical(symbol_clean, interval, days, exchange=exchange)
            if not df.empty:
                self._hist_cache[cache_key] = (df, time.time())
                return df
            logger.warning("Angel OHLCV failed for %s, trying NSE...", symbol_clean)

        # 2. NSE India free (equity only)
        if exchange in ("NSE", "BSE"):
            try:
                from_dt = (datetime.now() - timedelta(days=days)).strftime("%d-%m-%Y")
                to_dt = datetime.now().strftime("%d-%m-%Y")
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

        # 4. Dhan (equity only)
        if self._sources["dhan"] and interval == "day" and exchange in ("NSE", "BSE"):
            df = self.dhan.get_historical(symbol_clean, interval, days)
            if not df.empty:
                self._hist_cache[cache_key] = (df, time.time())
                return df

        logger.error("All historical sources failed for %s", symbol_clean)
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

        # 1. Angel SmartAPI (supports all segments)
        if self._sources["angel"]:
            try:
                quote = self.angel.get_quote(symbol_clean, exchange=exchange)
            except Exception:
                pass

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
            "timestamp": datetime.now().isoformat(),
            "fii_dii": fii_dii,
            "nifty_pcr": nifty_pcr,
            "bn_pcr": bn_pcr,
            "52w_highs": week52.get("52w_highs", []),
            "52w_lows": week52.get("52w_lows", []),
            "bulk_deals": bulk_deals,
            "quotes": quotes,
            "delivery": delivery,
            "fii_buying": fii_dii.get("fii_buying", True),
            "market_open": 9 <= datetime.now().hour < 16,
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
        for exch in ["NSE", "BSE", "MCX", "CDS", "NFO"]:
            try:
                instruments = kite.instruments(exch)
                for inst in instruments:
                    key = f"{exch}:{inst['tradingsymbol']}"
                    _instrument_cache[key] = inst["instrument_token"]
                logger.info("Loaded %d instruments for %s", len(instruments), exch)
            except Exception as e:
                logger.warning("Failed to load instruments for %s: %s", exch, e)

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

    to_date = datetime.now()
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
            logger.warning("Kite failed for %s: %s — falling back to yfinance", ticker, e)

    # Step 4: yfinance last resort
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
