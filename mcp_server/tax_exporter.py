"""
MKUMARAN Trading OS — Tax Export Module

Produces a per-trade P&L statement for Indian income-tax filing.
Covers all trade types the OS generates:
  - NSE/BSE equity (CNC delivery)
  - NSE/BSE intraday (MIS)
  - NFO/MCX/CDS futures & options (F&O)

Indian tax categories (FY 2025-26 rates — verify with your CA annually)
──────────────────────────────────────────────────────────────────────────
  INTRADAY_EQUITY   Speculative business income. Days held = 0 (same day).
                    Taxed as business income at slab rate.

  STCG_EQUITY       Short-term capital gain. Delivery equity, held < 1 year.
                    Rate: 20% (post-Budget 2024).

  LTCG_EQUITY       Long-term capital gain. Delivery equity, held ≥ 1 year.
                    Rate: 12.5% on gains above ₹1.25 lakh exemption.

  FNO               Futures & options. Non-speculative business income.
                    Taxed at slab rate; losses can be set off against
                    non-speculative business income for 8 years.

Per-trade cost breakdown
─────────────────────────
  STT               0.025% delivery sell / 0.0125% intraday sell
  Exchange charges  NSE 0.00345% / BSE 0.00375%
  SEBI fee          0.0001%
  Brokerage         ₹20 flat or 0.03% (whichever lower)
  GST               18% on (brokerage + exchange + SEBI)
  Stamp duty        0.015% on buy side

Usage
─────
  from mcp_server.tax_exporter import export_tax_statement

  # As JSON (for API response)
  result = export_tax_statement(fy="2025-26")

  # As CSV bytes (for download)
  result = export_tax_statement(fy="2025-26", fmt="csv")

  # Specific date range
  result = export_tax_statement(from_date="2025-04-01", to_date="2026-03-31")
"""

from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

logger = logging.getLogger(__name__)

# ── Tax constants ────────────────────────────────────────────
STCG_RATE      = Decimal("0.20")     # 20% post Budget 2024
LTCG_RATE      = Decimal("0.125")    # 12.5%
LTCG_EXEMPTION = Decimal("125000")   # ₹1.25L annual exemption
LTCG_DAYS      = 365                 # held ≥ 365 days = long-term

# Cost constants (keep in sync with backtester.py hygiene values)
BROKERAGE_FLAT   = Decimal("20")
BROKERAGE_PCT    = Decimal("0.0003")   # 0.03%
STT_DELIVERY     = Decimal("0.00025")  # 0.025% on sell side
STT_INTRADAY     = Decimal("0.000125") # 0.0125% on sell side
EXCHANGE_NSE     = Decimal("0.0000345")
EXCHANGE_BSE     = Decimal("0.0000375")
SEBI_FEE         = Decimal("0.000001")
GST_RATE         = Decimal("0.18")
STAMP_DUTY       = Decimal("0.00015")  # 0.015% on buy


# ── Trade classification ─────────────────────────────────────

TaxCategory = str  # "INTRADAY_EQUITY" | "STCG_EQUITY" | "LTCG_EQUITY" | "FNO"


def _classify(asset_class: str, timeframe: str, days_held: int) -> TaxCategory:
    """Classify a trade into its Indian income-tax category."""
    ac = (asset_class or "EQUITY").upper()
    tf = (timeframe or "1D").upper()

    # F&O first — non-speculative business income regardless of holding
    if ac in ("NFO", "FNO", "MCX", "CDS", "FOREX", "FX", "COMMODITY"):
        return "FNO"

    # Equity
    if days_held == 0 or tf in ("5M", "15M", "1H", "INTRADAY"):
        return "INTRADAY_EQUITY"

    if days_held < LTCG_DAYS:
        return "STCG_EQUITY"

    return "LTCG_EQUITY"


# ── Transaction cost computation ─────────────────────────────


def _costs(
    entry_price: Decimal,
    exit_price: Decimal,
    qty: int,
    exchange: str,
    tax_category: TaxCategory,
) -> dict[str, Decimal]:
    """Compute full Indian cost breakdown for one round-trip trade."""
    entry_turnover = entry_price * qty
    exit_turnover  = exit_price  * qty

    brokerage_entry = min(entry_turnover * BROKERAGE_PCT, BROKERAGE_FLAT)
    brokerage_exit  = min(exit_turnover  * BROKERAGE_PCT, BROKERAGE_FLAT)

    exc_charge = EXCHANGE_BSE if (exchange or "").upper() == "BSE" else EXCHANGE_NSE
    exc_entry  = entry_turnover * exc_charge
    exc_exit   = exit_turnover  * exc_charge

    sebi_entry = entry_turnover * SEBI_FEE
    sebi_exit  = exit_turnover  * SEBI_FEE

    gst_entry  = (brokerage_entry + exc_entry + sebi_entry) * GST_RATE
    gst_exit   = (brokerage_exit  + exc_exit  + sebi_exit)  * GST_RATE

    stamp      = entry_turnover * STAMP_DUTY

    is_intraday = tax_category == "INTRADAY_EQUITY"
    stt_rate = STT_INTRADAY if is_intraday else STT_DELIVERY
    stt = exit_turnover * stt_rate  # sell-side only

    total = (
        brokerage_entry + brokerage_exit
        + exc_entry + exc_exit
        + sebi_entry + sebi_exit
        + gst_entry + gst_exit
        + stamp + stt
    )

    return {
        "brokerage":      round(brokerage_entry + brokerage_exit, 2),
        "stt":            round(stt, 2),
        "exchange":       round(exc_entry + exc_exit, 2),
        "sebi":           round(sebi_entry + sebi_exit, 4),
        "gst":            round(gst_entry + gst_exit, 2),
        "stamp_duty":     round(stamp, 2),
        "total_charges":  round(total, 2),
    }


# ── Tax computation ──────────────────────────────────────────


def _tax_on_trade(net_pnl: Decimal, category: TaxCategory) -> Decimal:
    """Indicative tax on one trade's net P&L.

    This is an APPROXIMATION — actual tax depends on annual totals,
    slab rates, and offset rules. Intended for awareness, not filing.
    """
    if net_pnl <= 0:
        return Decimal("0")
    if category == "LTCG_EQUITY":
        return round(max(net_pnl - LTCG_EXEMPTION, Decimal("0")) * LTCG_RATE, 2)
    if category == "STCG_EQUITY":
        return round(net_pnl * STCG_RATE, 2)
    # INTRADAY_EQUITY and FNO: business income — tax at slab; approximate at 30%.
    return round(net_pnl * Decimal("0.30"), 2)


# ── Trade record ─────────────────────────────────────────────


@dataclass
class TaxTrade:
    """One closed trade as it appears in the tax statement."""
    signal_id: int
    ticker: str
    exchange: str
    asset_class: str
    direction: str
    entry_date: date
    exit_date: date
    days_held: int
    qty: int
    entry_price: Decimal
    exit_price: Decimal
    gross_pnl: Decimal
    charges: dict[str, Decimal]
    net_pnl: Decimal
    tax_category: TaxCategory
    indicative_tax: Decimal
    timeframe: str = "1D"
    pattern: str = ""

    def to_dict(self) -> dict:
        return {
            "signal_id":       self.signal_id,
            "ticker":          self.ticker,
            "exchange":        self.exchange,
            "asset_class":     self.asset_class,
            "direction":       self.direction,
            "entry_date":      str(self.entry_date),
            "exit_date":       str(self.exit_date),
            "days_held":       self.days_held,
            "qty":             self.qty,
            "entry_price":     float(self.entry_price),
            "exit_price":      float(self.exit_price),
            "gross_pnl":       float(self.gross_pnl),
            "brokerage":       float(self.charges["brokerage"]),
            "stt":             float(self.charges["stt"]),
            "exchange_charges":float(self.charges["exchange"]),
            "sebi":            float(self.charges["sebi"]),
            "gst":             float(self.charges["gst"]),
            "stamp_duty":      float(self.charges["stamp_duty"]),
            "total_charges":   float(self.charges["total_charges"]),
            "net_pnl":         float(self.net_pnl),
            "tax_category":    self.tax_category,
            "indicative_tax":  float(self.indicative_tax),
            "timeframe":       self.timeframe,
            "pattern":         self.pattern,
        }


# ── FY date helpers ──────────────────────────────────────────


def _fy_date_range(fy: str) -> tuple[date, date]:
    """Parse "2025-26" → (2025-04-01, 2026-03-31)."""
    try:
        parts = fy.split("-")
        start_year = int(parts[0])
        return date(start_year, 4, 1), date(start_year + 1, 3, 31)
    except Exception:
        raise ValueError(f"Invalid FY format: {fy!r}. Use YYYY-YY e.g. '2025-26'")


# ── Summary ──────────────────────────────────────────────────


@dataclass
class TaxSummary:
    fy: str
    from_date: date
    to_date: date
    trades: list[TaxTrade] = field(default_factory=list)

    def _filter(self, cat: TaxCategory) -> list[TaxTrade]:
        return [t for t in self.trades if t.tax_category == cat]

    @property
    def intraday(self)  -> list[TaxTrade]: return self._filter("INTRADAY_EQUITY")
    @property
    def stcg(self)      -> list[TaxTrade]: return self._filter("STCG_EQUITY")
    @property
    def ltcg(self)      -> list[TaxTrade]: return self._filter("LTCG_EQUITY")
    @property
    def fno(self)       -> list[TaxTrade]: return self._filter("FNO")

    def _totals(self, trades: list[TaxTrade]) -> dict:
        wins   = [t for t in trades if t.net_pnl > 0]
        losses = [t for t in trades if t.net_pnl <= 0]
        return {
            "count":           len(trades),
            "gross_pnl":       float(sum(t.gross_pnl for t in trades)),
            "total_charges":   float(sum(t.charges["total_charges"] for t in trades)),
            "net_pnl":         float(sum(t.net_pnl for t in trades)),
            "indicative_tax":  float(sum(t.indicative_tax for t in trades)),
            "wins":            len(wins),
            "losses":          len(losses),
            "win_rate":        round(len(wins) / len(trades) * 100, 1) if trades else 0,
        }

    def as_dict(self) -> dict:
        all_charges = sum(t.charges["total_charges"] for t in self.trades)
        return {
            "fy":          self.fy,
            "from_date":   str(self.from_date),
            "to_date":     str(self.to_date),
            "total_trades": len(self.trades),
            "summary": {
                "intraday_equity": self._totals(self.intraday),
                "stcg_equity":     self._totals(self.stcg),
                "ltcg_equity":     self._totals(self.ltcg),
                "fno":             self._totals(self.fno),
                "overall": {
                    "gross_pnl":      float(sum(t.gross_pnl for t in self.trades)),
                    "total_charges":  float(all_charges),
                    "net_pnl":        float(sum(t.net_pnl for t in self.trades)),
                    "indicative_tax": float(sum(t.indicative_tax for t in self.trades)),
                },
            },
            "trades": [t.to_dict() for t in self.trades],
            "disclaimer": (
                "Indicative tax values are APPROXIMATE. "
                "Actual tax depends on annual aggregates, slab rates, losses b/f, "
                "and set-off rules. Consult your CA for the final computation."
            ),
        }

    def as_csv(self) -> bytes:
        if not self.trades:
            return b""
        buf = io.StringIO()
        fieldnames = list(self.trades[0].to_dict().keys())
        writer = csv.DictWriter(buf, fieldnames=fieldnames)
        writer.writeheader()
        for t in self.trades:
            writer.writerow(t.to_dict())
        return buf.getvalue().encode("utf-8")


# ── Main export function ─────────────────────────────────────


def export_tax_statement(
    fy: str | None = None,
    from_date: str | date | None = None,
    to_date: str | date | None = None,
    fmt: str = "json",
) -> TaxSummary:
    """Load closed trades from Postgres and build a TaxSummary.

    Args:
        fy:        Financial year e.g. "2025-26". Mutually exclusive with
                   from_date / to_date.
        from_date: ISO date string or date object (inclusive).
        to_date:   ISO date string or date object (inclusive).
        fmt:       "json" (default) or "csv" — controls how callers
                   serialize the result (summary.as_dict() vs summary.as_csv()).

    Returns:
        TaxSummary (call .as_dict() or .as_csv() on it).
    """
    # Resolve date range
    if fy:
        fd, td = _fy_date_range(fy)
    else:
        fd = date.fromisoformat(str(from_date)) if from_date else date(date.today().year, 4, 1)
        td = date.fromisoformat(str(to_date))   if to_date   else date.today()
        fy = f"{fd.year}-{str(fd.year + 1)[2:]}"

    from mcp_server.db import SessionLocal
    from mcp_server.models import Outcome, Signal
    from sqlalchemy.orm import joinedload

    db = SessionLocal()
    try:
        rows = (
            db.query(Outcome, Signal)
            .join(Signal, Outcome.signal_id == Signal.id)
            .filter(Outcome.exit_date >= fd, Outcome.exit_date <= td)
            .options(joinedload(Outcome.signal))
            .order_by(Outcome.exit_date.asc(), Outcome.id.asc())
            .all()
        )
    finally:
        db.close()

    trades: list[TaxTrade] = []
    for outcome, sig in rows:
        try:
            entry_price = Decimal(str(sig.entry_price or 0))
            exit_price  = Decimal(str(outcome.exit_price or 0))
            qty         = int(sig.qty or 1)
            days_held   = int(outcome.days_held or 0)

            if entry_price <= 0 or exit_price <= 0 or qty <= 0:
                continue

            direction  = (sig.direction or "LONG").upper()
            asset_class = sig.asset_class or "EQUITY"
            timeframe   = sig.timeframe or "1D"
            exchange    = sig.exchange or "NSE"

            if direction in ("LONG", "BUY"):
                gross_pnl = (exit_price - entry_price) * qty
            else:
                gross_pnl = (entry_price - exit_price) * qty

            category = _classify(asset_class, timeframe, days_held)
            charges  = _costs(entry_price, exit_price, qty, exchange, category)
            net_pnl  = gross_pnl - charges["total_charges"]
            tax      = _tax_on_trade(net_pnl, category)

            entry_date = sig.signal_date or fd

            trades.append(TaxTrade(
                signal_id=sig.id,
                ticker=sig.ticker or "",
                exchange=exchange,
                asset_class=asset_class,
                direction=direction,
                entry_date=entry_date,
                exit_date=outcome.exit_date,
                days_held=days_held,
                qty=qty,
                entry_price=entry_price,
                exit_price=exit_price,
                gross_pnl=round(gross_pnl, 2),
                charges=charges,
                net_pnl=round(net_pnl, 2),
                tax_category=category,
                indicative_tax=tax,
                timeframe=timeframe,
                pattern=sig.pattern or "",
            ))
        except Exception as e:
            logger.warning("tax_exporter: skipping signal_id=%s — %s", getattr(sig, "id", "?"), e)

    logger.info(
        "tax_exporter: exported %d trades for FY %s (%s → %s)",
        len(trades), fy, fd, td,
    )
    return TaxSummary(fy=fy, from_date=fd, to_date=td, trades=trades)
