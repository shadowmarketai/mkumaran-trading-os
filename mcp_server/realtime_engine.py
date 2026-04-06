"""
MKUMARAN Trading OS — Real-Time Market Data Engine

4-layer architecture:
  1. TickCache   — Redis (optional) or in-memory dict for <1ms LTP reads
  2. GoodwillWebSocket / AngelWebSocket — live tick feeds
  3. PositionMonitor — instant SL/Target detection on every tick
  4. CandleBuilder — real-time OHLC candle construction

Replaces 60-second REST polling with sub-second WebSocket push.
"""

import json
import time
import logging
import threading
from datetime import datetime
from typing import Callable, Optional
from dataclasses import dataclass

try:
    import redis as _redis_lib
except ImportError:
    _redis_lib = None  # Redis is optional

try:
    import websocket as _ws_lib
except ImportError:
    _ws_lib = None

from mcp_server.config import settings

logger = logging.getLogger(__name__)


# ─── TICK DATA CLASS ──────────────────────────────────────────────────────────

@dataclass
class Tick:
    """Single market tick — same structure as Goodwill/Angel WebSocket push."""
    token: str
    symbol: str
    ltp: float
    open: float
    high: float
    low: float
    prev_close: float
    change: float
    pct_change: float
    volume: int
    avg_price: float
    buy_qty: int
    sell_qty: int
    oi: int = 0
    timestamp: str = ""


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 1 — TICK CACHE (Redis optional, in-memory dict fallback)
# ══════════════════════════════════════════════════════════════════════════════

class TickCache:
    """Redis-backed (or pure dict) tick cache. All reads <1ms."""

    def __init__(self, host: str = "localhost", port: int = 6379):
        self._memory: dict = {}
        self._available = False
        self.r = None

        if _redis_lib is not None:
            try:
                self.r = _redis_lib.Redis(
                    host=host, port=port, db=0,
                    decode_responses=True,
                    socket_connect_timeout=3,
                )
                self.r.ping()
                self._available = True
                logger.info("Redis connected for tick cache")
            except Exception:
                logger.info("Redis not available — using in-memory dict fallback")
                self.r = None
        else:
            logger.info("redis package not installed — using in-memory dict fallback")

    def set_tick(self, tick: Tick):
        data = {
            "ltp": tick.ltp,
            "open": tick.open,
            "high": tick.high,
            "low": tick.low,
            "prev_close": tick.prev_close,
            "change": tick.change,
            "pct_change": tick.pct_change,
            "volume": tick.volume,
            "oi": tick.oi,
            "timestamp": tick.timestamp or datetime.now().isoformat(),
        }
        key = f"tick:{tick.symbol}"
        if self._available and self.r:
            self.r.hset(key, mapping={k: str(v) for k, v in data.items()})
            self.r.expire(key, 3600)
        else:
            self._memory[key] = data

    def get_ltp(self, symbol: str) -> Optional[float]:
        key = f"tick:{symbol.replace('NSE:', '')}"
        try:
            if self._available and self.r:
                val = self.r.hget(key, "ltp")
                return float(val) if val else None
            else:
                return float(self._memory.get(key, {}).get("ltp", 0)) or None
        except Exception:
            return None

    def get_tick(self, symbol: str) -> Optional[dict]:
        key = f"tick:{symbol.replace('NSE:', '')}"
        try:
            if self._available and self.r:
                data = self.r.hgetall(key)
                if data:
                    return {k: float(v) if k != "timestamp" else v
                            for k, v in data.items()}
            else:
                return self._memory.get(key)
        except Exception:
            return None

    def get_multiple_ltps(self, symbols: list) -> dict:
        result = {}
        if self._available and self.r:
            pipe = self.r.pipeline()
            for sym in symbols:
                pipe.hget(f"tick:{sym.replace('NSE:', '')}", "ltp")
            values = pipe.execute()
            for sym, val in zip(symbols, values):
                result[sym] = float(val) if val else None
        else:
            for sym in symbols:
                result[sym] = self.get_ltp(sym)
        return result

    def publish_tick(self, symbol: str, ltp: float):
        if self._available and self.r:
            self.r.publish(
                "market_ticks",
                json.dumps({"symbol": symbol, "ltp": ltp,
                             "ts": datetime.now().isoformat()}),
            )


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 2 — GOODWILL WEBSOCKET (Primary live feed)
# ══════════════════════════════════════════════════════════════════════════════

class GoodwillWebSocket:
    """Goodwill API WebSocket for live tick streaming."""

    WS_URL = "wss://api.gwcindia.in/v1/websocket"

    def __init__(self, cache: TickCache, on_tick: Optional[Callable] = None):
        self.cache = cache
        self.on_tick = on_tick
        self.access_token: Optional[str] = None
        self.ws = None
        self.subscribed: list = []
        self.connected = False
        self._reconnect_delay = 5

    def _login(self) -> bool:
        """Get GWC access token using credentials from project settings."""
        if not settings.GWC_API_KEY:
            logger.warning("GWC_API_KEY not configured — Goodwill WebSocket disabled")
            return False
        try:
            import pyotp
            import requests

            totp = pyotp.TOTP(settings.GWC_API_SECRET).now()
            resp = requests.post(
                "https://api.gwcindia.in/v1/login",
                json={
                    "client_id": settings.GWC_CLIENT_ID,
                    "password": settings.GWC_API_SECRET,
                    "totp": totp,
                },
                headers={"x-api-key": settings.GWC_API_KEY},
                timeout=10,
            )
            data = resp.json()
            if data.get("status") == "success":
                self.access_token = data["data"]["access_token"]
                return True
            logger.warning("Goodwill login response: %s", data.get("message", "unknown"))
        except Exception as e:
            logger.warning("Goodwill login failed: %s", e)
        return False

    def _parse_tick(self, raw: dict) -> Optional[Tick]:
        try:
            symbol = raw.get("symbol", raw.get("sym", ""))
            ltp = float(raw.get("lp", raw.get("ltp", 0)))
            prev = float(raw.get("c", raw.get("prev_close", 0)))
            return Tick(
                token=str(raw.get("token", "")),
                symbol=symbol,
                ltp=ltp,
                open=float(raw.get("o", 0)),
                high=float(raw.get("h", 0)),
                low=float(raw.get("l", 0)),
                prev_close=prev,
                change=round(ltp - prev, 2),
                pct_change=round(((ltp - prev) / max(prev, 1)) * 100, 2),
                volume=int(raw.get("v", 0)),
                avg_price=float(raw.get("ap", 0)),
                buy_qty=int(raw.get("tbq", 0)),
                sell_qty=int(raw.get("tsq", 0)),
                oi=int(raw.get("oi", 0)),
                timestamp=datetime.now().isoformat(),
            )
        except Exception as e:
            logger.debug("Tick parse error: %s", e)
            return None

    def _on_message(self, ws, message):
        try:
            raw = json.loads(message)
            tick = self._parse_tick(raw)
            if tick and tick.ltp > 0:
                self.cache.set_tick(tick)
                self.cache.publish_tick(tick.symbol, tick.ltp)
                if self.on_tick:
                    self.on_tick(tick)
        except Exception as e:
            logger.debug("WS message handler error: %s", e)

    def _on_open(self, ws):
        self.connected = True
        logger.info("Goodwill WebSocket connected")
        if self.subscribed:
            ws.send(json.dumps({
                "action": "subscribe",
                "symbols": self.subscribed,
                "token": self.access_token,
                "api_key": settings.GWC_API_KEY,
            }))
            logger.info("Subscribed to %d symbols via Goodwill WS", len(self.subscribed))

    def _on_error(self, ws, error):
        logger.warning("Goodwill WS error: %s", error)
        self.connected = False

    def _on_close(self, ws, code, msg):
        logger.warning("Goodwill WS closed (%s) — reconnecting in %ds", code, self._reconnect_delay)
        self.connected = False
        time.sleep(self._reconnect_delay)
        self.connect(self.subscribed)

    def connect(self, symbols: list):
        if _ws_lib is None:
            logger.warning("websocket-client not installed — Goodwill WS disabled")
            return
        self.subscribed = symbols
        if not self.access_token:
            if not self._login():
                return
        self.ws = _ws_lib.WebSocketApp(
            self.WS_URL,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )
        thread = threading.Thread(
            target=self.ws.run_forever,
            kwargs={"ping_interval": 30, "ping_timeout": 10},
            daemon=True,
        )
        thread.start()
        logger.info("Goodwill WS thread started for %d symbols", len(symbols))

    def subscribe(self, symbols: list):
        new_syms = [s for s in symbols if s not in self.subscribed]
        if new_syms and self.ws and self.connected:
            self.subscribed.extend(new_syms)
            self.ws.send(json.dumps({
                "action": "subscribe",
                "symbols": new_syms,
                "token": self.access_token,
                "api_key": settings.GWC_API_KEY,
            }))
            logger.info("Subscribed to additional symbols: %s", new_syms)

    def unsubscribe(self, symbols: list):
        if self.ws and self.connected:
            self.subscribed = [s for s in self.subscribed if s not in symbols]
            self.ws.send(json.dumps({
                "action": "unsubscribe",
                "symbols": symbols,
            }))


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 2B — ANGEL SMARTAPI WEBSOCKET (Fallback)
# ══════════════════════════════════════════════════════════════════════════════

class AngelWebSocket:
    """Angel SmartAPI WebSocket — fallback if Goodwill WS fails."""

    def __init__(self, cache: TickCache, on_tick: Optional[Callable] = None):
        self.cache = cache
        self.on_tick = on_tick
        self.ws = None

    def connect(self, tokens: list):
        if not settings.ANGEL_API_KEY:
            logger.warning("ANGEL_API_KEY not configured — Angel WS disabled")
            return
        try:
            from SmartApi.SmartWebSocketV2 import SmartWebSocketV2

            # Reuse existing angel_auth for TOTP login + token caching
            from mcp_server.angel_auth import get_authenticated_angel, _load_cached_token
            client = get_authenticated_angel()

            cached = _load_cached_token()
            if not cached:
                logger.warning("Angel token not cached — cannot start WS feed")
                return

            auth_token = cached["jwt_token"]
            feed_token = cached.get("feed_token", "")
            if not feed_token:
                feed_token = client.getfeedToken()

            cache_ref = self.cache
            on_tick_ref = self.on_tick

            def on_data(wsapp, message):
                try:
                    tick_data = json.loads(message)
                    for item in (tick_data if isinstance(tick_data, list) else [tick_data]):
                        token = str(item.get("token", ""))
                        ltp = float(item.get("last_traded_price", 0)) / 100
                        prev = float(item.get("close_price", 0)) / 100
                        tick = Tick(
                            token=token,
                            symbol=item.get("trading_symbol", token),
                            ltp=ltp,
                            open=float(item.get("open_price_of_the_day", 0)) / 100,
                            high=float(item.get("high_price_of_the_day", 0)) / 100,
                            low=float(item.get("low_price_of_the_day", 0)) / 100,
                            prev_close=prev,
                            change=round(ltp - prev, 2),
                            pct_change=round(((ltp - prev) / max(prev, 1)) * 100, 2),
                            volume=int(item.get("volume_trade_for_the_day", 0)),
                            avg_price=float(item.get("average_trade_price", 0)) / 100,
                            buy_qty=int(item.get("total_buy_quantity", 0)),
                            sell_qty=int(item.get("total_sell_quantity", 0)),
                            oi=int(item.get("open_interest", 0)),
                            timestamp=datetime.now().isoformat(),
                        )
                        cache_ref.set_tick(tick)
                        cache_ref.publish_tick(tick.symbol, tick.ltp)
                        if on_tick_ref:
                            on_tick_ref(tick)
                except Exception as e:
                    logger.debug("Angel tick parse: %s", e)

            self.ws = SmartWebSocketV2(
                auth_token, settings.ANGEL_API_KEY,
                settings.ANGEL_CLIENT_ID, feed_token,
            )
            self.ws.on_data = on_data
            self.ws.on_open = lambda ws: logger.info("Angel WebSocket connected")
            self.ws.on_error = lambda ws, e: logger.warning("Angel WS error: %s", e)

            token_list = [{"exchangeType": 1, "tokens": tokens}]
            self.ws.subscribe("session", 3, token_list)
            logger.info("Angel WebSocket subscribed to %d tokens", len(tokens))

        except ImportError:
            logger.warning("smartapi-python not installed — Angel WS disabled")
        except Exception as e:
            logger.warning("Angel WebSocket failed: %s", e)


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 3 — POSITION MONITOR (instant SL/Target on every tick)
# ══════════════════════════════════════════════════════════════════════════════

class PositionMonitor:
    """Real-time position monitor — checks SL/Target on every incoming tick."""

    def __init__(self, cache: TickCache):
        self.cache = cache
        self.positions: dict = {}
        self._lock = threading.Lock()

    def add_position(self, symbol: str, entry: float, sl: float,
                     target: float, qty: int, direction: str = "LONG"):
        with self._lock:
            self.positions[symbol] = {
                "symbol": symbol,
                "entry": entry,
                "sl": sl,
                "target": target,
                "qty": qty,
                "direction": direction,
                "added_at": datetime.now().isoformat(),
                "pnl": 0.0,
                "status": "OPEN",
            }
        logger.info("Monitoring: %s | Entry: %s | SL: %s | T: %s", symbol, entry, sl, target)

    def remove_position(self, symbol: str):
        with self._lock:
            self.positions.pop(symbol, None)

    def on_tick(self, tick: Tick):
        """Called on every tick — core real-time monitor (<5ms)."""
        symbol = tick.symbol
        if symbol not in self.positions:
            return

        pos = self.positions[symbol]
        if pos["status"] != "OPEN":
            return

        ltp = tick.ltp

        if pos["direction"] == "LONG":
            pnl = (ltp - pos["entry"]) * pos["qty"]
        else:
            pnl = (pos["entry"] - ltp) * pos["qty"]

        with self._lock:
            self.positions[symbol]["pnl"] = round(pnl, 2)

        # Check Stop Loss
        if pos["direction"] == "LONG" and ltp <= pos["sl"]:
            self._trigger_exit(pos, ltp, "STOP_LOSS", pnl)
        elif pos["direction"] == "SHORT" and ltp >= pos["sl"]:
            self._trigger_exit(pos, ltp, "STOP_LOSS", pnl)
        # Check Target
        elif pos["direction"] == "LONG" and ltp >= pos["target"]:
            self._trigger_exit(pos, ltp, "TARGET_HIT", pnl)
        elif pos["direction"] == "SHORT" and ltp <= pos["target"]:
            self._trigger_exit(pos, ltp, "TARGET_HIT", pnl)

    def _trigger_exit(self, pos: dict, exit_price: float,
                      reason: str, pnl: float):
        symbol = pos["symbol"]

        with self._lock:
            if self.positions.get(symbol, {}).get("status") != "OPEN":
                return
            self.positions[symbol]["status"] = "TRIGGERED"

        pnl_str = f"+{pnl:.0f}" if pnl >= 0 else f"{pnl:.0f}"
        label = "TARGET HIT" if reason == "TARGET_HIT" else "STOP LOSS"
        msg = (
            f"{'TARGET HIT' if reason == 'TARGET_HIT' else 'STOP LOSS'} -- {symbol}\n"
            f"Entry: {pos['entry']} | Exit: {exit_price} | Qty: {pos['qty']}\n"
            f"P&L: {pnl_str} | {label}"
        )

        # Send Telegram alert via existing project infrastructure
        self._send_telegram_alert(msg)

        # Log exit to DB via SQLAlchemy ORM
        threading.Thread(
            target=self._log_exit_to_db,
            args=(pos, exit_price, reason, pnl),
            daemon=True,
        ).start()

        self.remove_position(symbol)
        logger.info("Exit triggered: %s | %s | P&L: %s", symbol, reason, pnl_str)

    def _send_telegram_alert(self, msg: str):
        """Send via existing send_telegram_message (async), using _fire_and_forget."""
        try:
            from mcp_server.telegram_bot import send_telegram_message
            from mcp_server.mcp_server import _fire_and_forget
            _fire_and_forget(send_telegram_message(msg, force=True))
        except Exception as e:
            logger.warning("Telegram alert failed: %s", e)

    def _log_exit_to_db(self, pos: dict, exit_price: float,
                        reason: str, pnl: float):
        """Log trade exit using SQLAlchemy ORM."""
        try:
            from mcp_server.db import SessionLocal
            from mcp_server.models import ActiveTrade
            db = SessionLocal()
            try:
                trade = db.query(ActiveTrade).filter(
                    ActiveTrade.ticker == f"NSE:{pos['symbol']}",
                ).first()
                if trade:
                    trade.current_price = exit_price
                    trade.alert_sent = True
                    trade.last_updated = datetime.now()
                    db.commit()
                    logger.info("DB updated for %s exit (%s)", pos["symbol"], reason)
            finally:
                db.close()
        except Exception as e:
            logger.warning("DB exit log failed: %s", e)

    def get_positions_summary(self) -> list:
        summary = []
        with self._lock:
            for symbol, pos in self.positions.items():
                ltp = self.cache.get_ltp(symbol)
                if ltp:
                    if pos["direction"] == "LONG":
                        pnl = (ltp - pos["entry"]) * pos["qty"]
                    else:
                        pnl = (pos["entry"] - ltp) * pos["qty"]
                    summary.append({**pos, "ltp": ltp, "pnl": round(pnl, 2)})
                else:
                    summary.append(pos)
        return summary


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 4 — CANDLE BUILDER (Build OHLC candles from live ticks)
# ══════════════════════════════════════════════════════════════════════════════

class CandleBuilder:
    """Builds OHLC candles from live tick stream."""

    INTERVALS = {
        "1minute": 60,
        "5minute": 300,
        "15minute": 900,
        "60minute": 3600,
    }

    def __init__(self, on_candle_close: Optional[Callable] = None):
        self.on_candle_close = on_candle_close
        self._candles: dict = {}

    def _get_candle_key(self, ts: datetime, interval_secs: int) -> int:
        epoch = int(ts.timestamp())
        return (epoch // interval_secs) * interval_secs

    def on_tick(self, tick: Tick):
        if tick.ltp <= 0:
            return

        now = datetime.now()
        symbol = tick.symbol
        ltp = tick.ltp

        for interval_name, secs in self.INTERVALS.items():
            key = self._get_candle_key(now, secs)
            sym_key = f"{symbol}_{interval_name}"

            if sym_key not in self._candles:
                self._candles[sym_key] = {}

            candles = self._candles[sym_key]

            if key not in candles:
                if candles:
                    last_key = max(candles.keys())
                    closed_candle = candles[last_key]
                    closed_candle["closed"] = True
                    if self.on_candle_close:
                        threading.Thread(
                            target=self.on_candle_close,
                            args=(symbol, interval_name, closed_candle),
                            daemon=True,
                        ).start()

                candles[key] = {
                    "symbol": symbol,
                    "interval": interval_name,
                    "timestamp": datetime.fromtimestamp(key).isoformat(),
                    "open": ltp,
                    "high": ltp,
                    "low": ltp,
                    "close": ltp,
                    "volume": tick.volume,
                    "closed": False,
                }
                old_keys = sorted(candles.keys())[:-2]
                for k in old_keys:
                    del candles[k]
            else:
                c = candles[key]
                c["high"] = max(c["high"], ltp)
                c["low"] = min(c["low"], ltp)
                c["close"] = ltp
                c["volume"] = tick.volume

    def get_latest_candle(self, symbol: str,
                          interval: str = "5minute") -> Optional[dict]:
        sym_key = f"{symbol}_{interval}"
        candles = self._candles.get(sym_key, {})
        if candles:
            latest_key = max(candles.keys())
            return candles[latest_key]
        return None


# ══════════════════════════════════════════════════════════════════════════════
# MASTER REALTIME ENGINE
# ══════════════════════════════════════════════════════════════════════════════

class RealtimeEngine:
    """
    Orchestrates WebSocket feeds, tick cache, position monitoring,
    and candle building. Gracefully degrades when dependencies are missing.
    """

    INDEX_TOKENS = {
        "NIFTY": "26000",
        "BANKNIFTY": "26009",
        "FINNIFTY": "26037",
        "SENSEX": "1",
    }

    def __init__(self):
        redis_host = getattr(settings, "REDIS_HOST", "localhost")
        redis_port = getattr(settings, "REDIS_PORT", 6379)
        self.cache = TickCache(host=redis_host, port=redis_port)
        self.monitor = PositionMonitor(self.cache)
        self.candles = CandleBuilder(on_candle_close=self._on_candle_close)
        self.gwc_ws: Optional[GoodwillWebSocket] = None
        self.angel_ws: Optional[AngelWebSocket] = None
        self._active = False
        self._subscribed_symbols: list = []

    def _on_tick(self, tick: Tick):
        self.monitor.on_tick(tick)
        self.candles.on_tick(tick)

    def _on_candle_close(self, symbol: str, interval: str, candle: dict):
        logger.info(
            "Candle closed: %s %s | O/H/L/C: %.0f/%.0f/%.0f/%.0f",
            symbol, interval,
            candle["open"], candle["high"], candle["low"], candle["close"],
        )
        if interval == "15minute" and self._is_market_hours():
            threading.Thread(
                target=self._run_smc_on_candle,
                args=(symbol, candle),
                daemon=True,
            ).start()

    def _run_smc_on_candle(self, symbol: str, candle: dict):
        try:
            import pandas as pd
            from mcp_server.smart_money_concepts import CRTEngine
            crt = CRTEngine()
            row = pd.Series(candle)
            result = crt.analyse_candle(row, symbol, "15minute")
            if result.crt_pattern in ("TYPE1_BULL", "TYPE2_BEAR"):
                logger.info("CRT pattern on candle close: %s -> %s", symbol, result.crt_pattern)
        except Exception as e:
            logger.debug("SMC candle analysis: %s", e)

    def _is_market_hours(self) -> bool:
        from mcp_server.market_calendar import is_market_open
        return is_market_open("NSE")

    def _load_active_trades(self):
        """Load open positions from DB and register them with PositionMonitor."""
        try:
            from mcp_server.db import SessionLocal
            from mcp_server.models import ActiveTrade
            from sqlalchemy.orm import joinedload
            db = SessionLocal()
            try:
                trades = db.query(ActiveTrade).options(
                    joinedload(ActiveTrade.signal),
                ).all()
                for t in trades:
                    symbol = t.ticker.replace("NSE:", "") if t.ticker else ""
                    if not symbol:
                        continue
                    entry = float(t.entry_price) if t.entry_price else 0
                    sl = float(t.stop_loss) if t.stop_loss else 0
                    target = float(t.target) if t.target else 0
                    direction = "LONG"
                    if t.signal and t.signal.direction in ("SELL", "SHORT"):
                        direction = "SHORT"
                    qty = t.signal.qty if t.signal and t.signal.qty else 1
                    self.monitor.add_position(symbol, entry, sl, target, qty, direction)
                    if symbol not in self._subscribed_symbols:
                        self._subscribed_symbols.append(symbol)
                logger.info("Loaded %d active trades for real-time monitoring", len(trades))
            finally:
                db.close()
        except Exception as e:
            logger.warning("Could not load active trades: %s", e)

    def _load_watchlist_symbols(self):
        """Load Tier 2 watchlist symbols for subscription."""
        try:
            from mcp_server.db import SessionLocal
            from mcp_server.models import Watchlist
            db = SessionLocal()
            try:
                items = db.query(Watchlist).filter(
                    Watchlist.active.is_(True),
                    Watchlist.tier == 2,
                ).all()
                for item in items:
                    symbol = item.ticker.replace("NSE:", "") if item.ticker else ""
                    if symbol and symbol not in self._subscribed_symbols:
                        self._subscribed_symbols.append(symbol)
                logger.info("Loaded %d Tier 2 watchlist symbols", len(items))
            finally:
                db.close()
        except Exception as e:
            logger.warning("Could not load watchlist: %s", e)

    def start(self, extra_symbols: Optional[list] = None):
        """Start the real-time engine (blocking WebSocket connect)."""
        self._active = True

        # Load symbols from DB
        self._load_active_trades()
        self._load_watchlist_symbols()

        # Add any extra symbols
        if extra_symbols:
            for s in extra_symbols:
                if s not in self._subscribed_symbols:
                    self._subscribed_symbols.append(s)

        # Always include indices
        for idx in ("NIFTY", "BANKNIFTY"):
            if idx not in self._subscribed_symbols:
                self._subscribed_symbols.append(idx)

        symbols = self._subscribed_symbols
        logger.info("Starting RealtimeEngine for %d symbols", len(symbols))

        # Primary: Goodwill WebSocket
        self.gwc_ws = GoodwillWebSocket(cache=self.cache, on_tick=self._on_tick)
        self.gwc_ws.connect(symbols)

        # Fallback: Angel WebSocket (if Goodwill fails)
        if settings.ANGEL_API_KEY:
            time.sleep(2)
            if not self.gwc_ws.connected:
                logger.info("Goodwill WS not connected — trying Angel fallback")
                self.angel_ws = AngelWebSocket(self.cache, self._on_tick)
                tokens = [self.INDEX_TOKENS.get(s, s) for s in symbols]
                self.angel_ws.connect(tokens)

        logger.info("RealtimeEngine started (%d symbols)", len(symbols))

    def start_async(self):
        """Start in a background daemon thread (non-blocking)."""
        thread = threading.Thread(target=self.start, daemon=True, name="RealtimeEngine")
        thread.start()

    def stop(self):
        self._active = False
        if self.gwc_ws and self.gwc_ws.ws:
            try:
                self.gwc_ws.ws.close()
            except Exception:
                pass
        logger.info("RealtimeEngine stopped")

    def add_to_watchlist(self, symbol: str):
        if symbol not in self._subscribed_symbols:
            self._subscribed_symbols.append(symbol)
            if self.gwc_ws:
                self.gwc_ws.subscribe([symbol])

    def remove_from_watchlist(self, symbol: str):
        if symbol in self._subscribed_symbols:
            self._subscribed_symbols.remove(symbol)
            if self.gwc_ws:
                self.gwc_ws.unsubscribe([symbol])

    # ── Convenience methods ──────────────────────────────────────────────────

    def get_ltp(self, symbol: str) -> Optional[float]:
        return self.cache.get_ltp(symbol.replace("NSE:", ""))

    def get_multiple_ltps(self, symbols: list) -> dict:
        return self.cache.get_multiple_ltps(symbols)

    def get_positions_summary(self) -> list:
        return self.monitor.get_positions_summary()

    def get_latest_candle(self, symbol: str,
                          interval: str = "15minute") -> Optional[dict]:
        return self.candles.get_latest_candle(symbol.replace("NSE:", ""), interval)
