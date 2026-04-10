"""
MKUMARAN Trading OS — Signal Validation Engine

Validates actual past signals against historical OHLCV data to determine
real win rate. Different from backtester.py which tests strategies —
this validates YOUR actual signals that were generated.

Answers: "Of the 200 signals my system generated, how many actually hit target vs SL?"

Breakdowns by: pattern, direction, MWA alignment, exchange, timeframe, month.
"""

import logging
import statistics
from dataclasses import dataclass, field
from datetime import date, timedelta


logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Single validated signal."""
    signal_id: int
    ticker: str
    exchange: str
    direction: str
    pattern: str
    timeframe: str
    entry_price: float
    stop_loss: float
    target: float
    rrr: float
    ai_confidence: float
    mwa_score: str
    signal_date: str
    outcome: str = ""           # WIN, LOSS, EXPIRED
    exit_price: float = 0.0
    days_held: int = 0
    pnl_pct: float = 0.0
    max_favorable_pct: float = 0.0
    max_adverse_pct: float = 0.0


@dataclass
class ValidationReport:
    """Full validation report."""
    total: int = 0
    validated: int = 0
    skipped: int = 0
    wins: int = 0
    losses: int = 0
    expired: int = 0
    win_rate: float = 0.0
    avg_pnl: float = 0.0
    avg_winner: float = 0.0
    avg_loser: float = 0.0
    profit_factor: float = 0.0
    expectancy: float = 0.0
    sharpe: float = 0.0
    max_drawdown: float = 0.0
    by_pattern: list = field(default_factory=list)
    by_direction: list = field(default_factory=list)
    by_exchange: list = field(default_factory=list)
    by_mwa: list = field(default_factory=list)
    by_month: list = field(default_factory=list)
    trades: list = field(default_factory=list)
    equity_curve: list = field(default_factory=list)
    period: str = ""


def _simulate(entry: float, sl: float, tgt: float, direction: str,
              bars: list[dict], max_days: int = 30) -> dict:
    """Walk bars to check if target or SL hits first."""
    is_long = direction.upper() in ("LONG", "BUY")
    mfe = 0.0
    mae = 0.0

    for i, bar in enumerate(bars[:max_days]):
        high = bar.get("high", 0)
        low = bar.get("low", 0)

        if is_long:
            mfe = max(mfe, (high - entry) / entry * 100) if high else mfe
            mae = max(mae, (entry - low) / entry * 100) if low else mae
            if low <= sl:
                return {"outcome": "LOSS", "exit": sl, "days": i+1,
                        "pnl": round((sl - entry) / entry * 100, 2), "mfe": round(mfe, 2), "mae": round(mae, 2)}
            if high >= tgt:
                return {"outcome": "WIN", "exit": tgt, "days": i+1,
                        "pnl": round((tgt - entry) / entry * 100, 2), "mfe": round(mfe, 2), "mae": round(mae, 2)}
        else:
            mfe = max(mfe, (entry - low) / entry * 100) if low else mfe
            mae = max(mae, (high - entry) / entry * 100) if high else mae
            if high >= sl:
                return {"outcome": "LOSS", "exit": sl, "days": i+1,
                        "pnl": round((entry - sl) / entry * 100, 2), "mfe": round(mfe, 2), "mae": round(mae, 2)}
            if low <= tgt:
                return {"outcome": "WIN", "exit": tgt, "days": i+1,
                        "pnl": round((entry - tgt) / entry * 100, 2), "mfe": round(mfe, 2), "mae": round(mae, 2)}

    last_c = bars[-1].get("close", entry) if bars else entry
    pnl = ((last_c - entry) / entry * 100) if is_long else ((entry - last_c) / entry * 100)
    return {"outcome": "EXPIRED", "exit": last_c, "days": len(bars),
            "pnl": round(pnl, 2), "mfe": round(mfe, 2), "mae": round(mae, 2)}


def _group_by(results: list[ValidationResult], key: str) -> list[dict]:
    groups: dict[str, list] = {}
    for r in results:
        v = getattr(r, key, "?") or "?"
        groups.setdefault(v, []).append(r)

    out = []
    for name, g in sorted(groups.items()):
        w = sum(1 for x in g if x.outcome == "WIN")
        t = len(g)
        pnls = [x.pnl_pct for x in g]
        gp = sum(p for p in pnls if p > 0)
        gl = abs(sum(p for p in pnls if p < 0))
        out.append({
            "name": name, "total": t, "wins": w,
            "win_rate": round(w / t * 100, 1) if t else 0,
            "avg_pnl": round(sum(pnls) / t, 2) if t else 0,
            "profit_factor": round(gp / gl, 2) if gl else 0,
        })
    return sorted(out, key=lambda x: x["win_rate"], reverse=True)


def validate_signals(db_session, days: int = 90, max_holding: int = 30) -> ValidationReport:
    """Validate all signals from the last N days against real price data."""
    from sqlalchemy import text

    cutoff = (date.today() - timedelta(days=days)).isoformat()
    rows = db_session.execute(text(
        """SELECT id, signal_date, ticker, exchange, direction, pattern,
                  entry_price, stop_loss, target, rrr, ai_confidence,
                  mwa_score, timeframe
           FROM signals WHERE signal_date >= :cutoff ORDER BY signal_date"""
    ), {"cutoff": cutoff}).mappings().all()

    signals = [dict(r) for r in rows]
    report = ValidationReport(total=len(signals))

    if not signals:
        return report

    results: list[ValidationResult] = []
    equity = 100000.0
    curve = [{"date": "", "equity": equity}]

    for sig in signals:
        entry = float(sig.get("entry_price", 0) or 0)
        sl = float(sig.get("stop_loss", 0) or 0)
        tgt = float(sig.get("target", 0) or 0)
        if entry <= 0 or sl <= 0 or tgt <= 0:
            report.skipped += 1
            continue

        # Fetch OHLCV
        try:
            from mcp_server.data_provider import get_provider
            from datetime import datetime
            provider = get_provider()
            sd = sig["signal_date"]
            if isinstance(sd, str):
                sd = datetime.strptime(sd, "%Y-%m-%d").date()
            start = sd + timedelta(days=1)
            end = start + timedelta(days=max_holding + 10)
            df = provider.get_ohlcv(sig["ticker"], interval="day", from_date=start, to_date=end)
            if df is None or df.empty:
                report.skipped += 1
                continue
            bars = [{"high": float(r.get("high", 0)), "low": float(r.get("low", 0)),
                     "close": float(r.get("close", 0))} for _, r in df.iterrows()]
        except Exception:
            report.skipped += 1
            continue

        sim = _simulate(entry, sl, tgt, sig["direction"], bars, max_holding)
        risk = abs(entry - sl)
        reward = abs(tgt - entry)

        vr = ValidationResult(
            signal_id=sig["id"], ticker=sig["ticker"], exchange=sig.get("exchange", "NSE"),
            direction=sig["direction"], pattern=sig.get("pattern", ""), timeframe=sig.get("timeframe", "1D"),
            entry_price=entry, stop_loss=sl, target=tgt,
            rrr=round(reward / risk, 2) if risk else 0,
            ai_confidence=float(sig.get("ai_confidence", 0) or 0),
            mwa_score=sig.get("mwa_score", ""),
            signal_date=str(sig["signal_date"]),
            outcome=sim["outcome"], exit_price=sim["exit"], days_held=sim["days"],
            pnl_pct=sim["pnl"], max_favorable_pct=sim["mfe"], max_adverse_pct=sim["mae"],
        )
        results.append(vr)

        pos_size = equity * 0.02
        equity += pos_size * sim["pnl"] / 100
        curve.append({"date": str(sig["signal_date"]), "equity": round(equity, 2)})

    report.validated = len(results)
    report.trades = [vars(r) for r in results]
    report.equity_curve = curve

    if not results:
        return report

    report.wins = sum(1 for r in results if r.outcome == "WIN")
    report.losses = sum(1 for r in results if r.outcome == "LOSS")
    report.expired = sum(1 for r in results if r.outcome == "EXPIRED")
    report.win_rate = round(report.wins / report.validated * 100, 1)

    pnls = [r.pnl_pct for r in results]
    winners = [r.pnl_pct for r in results if r.outcome == "WIN"]
    losers = [r.pnl_pct for r in results if r.outcome == "LOSS"]

    report.avg_pnl = round(sum(pnls) / len(pnls), 2)
    report.avg_winner = round(sum(winners) / len(winners), 2) if winners else 0
    report.avg_loser = round(sum(losers) / len(losers), 2) if losers else 0

    gp = sum(p for p in pnls if p > 0)
    gl = abs(sum(p for p in pnls if p < 0))
    report.profit_factor = round(gp / gl, 2) if gl else 0

    if report.validated > 0:
        wp = report.wins / report.validated
        lp = report.losses / report.validated
        report.expectancy = round(wp * report.avg_winner + lp * report.avg_loser, 2)

    if len(pnls) > 1:
        m = statistics.mean(pnls)
        s = statistics.stdev(pnls)
        report.sharpe = round((m / s) * (252 ** 0.5), 2) if s else 0

    peak = curve[0]["equity"]
    mdd = 0.0
    for p in curve:
        if p["equity"] > peak:
            peak = p["equity"]
        dd = (peak - p["equity"]) / peak * 100
        mdd = max(mdd, dd)
    report.max_drawdown = round(mdd, 2)

    report.by_pattern = _group_by(results, "pattern")
    report.by_direction = _group_by(results, "direction")
    report.by_exchange = _group_by(results, "exchange")
    report.by_mwa = _group_by(results, "mwa_score")
    report.by_month = _monthly(results)
    report.period = f"{min(r.signal_date for r in results)} to {max(r.signal_date for r in results)}"

    return report


def _monthly(results: list[ValidationResult]) -> list[dict]:
    months: dict[str, list] = {}
    for r in results:
        k = r.signal_date[:7] if r.signal_date else "?"
        months.setdefault(k, []).append(r)
    out = []
    for m, g in sorted(months.items()):
        w = sum(1 for x in g if x.outcome == "WIN")
        t = len(g)
        pnls = [x.pnl_pct for x in g]
        out.append({"month": m, "trades": t, "wins": w,
                     "win_rate": round(w / t * 100, 1), "pnl": round(sum(pnls), 2)})
    return out
