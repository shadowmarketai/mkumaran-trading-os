"""Signal card formatters for Telegram messages."""
import logging

from mcp_server.money import Numeric, to_money

logger = logging.getLogger(__name__)


def format_buy_signal(
    signal_id: int,
    ticker: str,
    company_name: str,
    entry_price: Numeric,
    stop_loss: Numeric,
    target: Numeric,
    rrr: Numeric,
    qty: int,
    risk_amt: Numeric,
    pattern: str,
    ai_confidence: int,
    ai_reasoning: str,
    mwa_direction: str,
    scanner_count: int,
    tv_confirmed: bool,
    tier: int,
    source: str,
    ltrp: Numeric = 0,
    technical_summary: str = "",
    fundamental_screen: dict | None = None,
    boosts: list[str] | None = None,
) -> str:
    """Format a BUY signal card for Telegram.

    Accepts Numeric for money fields so callers can pass Decimal (from
    RRMSResult/DB) or float (legacy) without wrapping. All internal
    arithmetic runs in Decimal to keep the upside% exact.
    """
    entry_price = to_money(entry_price)
    stop_loss = to_money(stop_loss)
    target = to_money(target)
    risk_amt = to_money(risk_amt)
    ltrp_d = to_money(ltrp)
    tv_badge = " \u00b7 TV CONFIRMED" if tv_confirmed else ""
    total_cost = qty * entry_price
    upside_pct = round((target - entry_price) / entry_price * 100, 1)
    ltrp_suffix = f" \u00b7 within 2% of LTRP \u20b9{ltrp_d:,.2f}" if ltrp_d else ""

    card = f"""\U0001f7e2 BUY SIGNAL \u2014 SWING TRADE{tv_badge}
Tier {tier} \u00b7 {source} \u00b7 #{signal_id:03d}
\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501
Stock   : {company_name} \u00b7 {ticker}
Entry   : \u20b9{entry_price:,.2f}{ltrp_suffix}
Target  : \u20b9{target:,.2f} \u00b7 (+{upside_pct}%) \u2705
SL      : \u20b9{stop_loss:,.2f} \u00b7 0.5% below LTRP
RRR     : {rrr:.1f}:1 \u00b7 RRMS APPROVED \u2705
Qty     : {qty} shares \u00b7 \u20b9{total_cost:,.0f} \u00b7 Risk: \u20b9{risk_amt:,.0f}
Pattern : {pattern}
\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501
MWA     : {mwa_direction} ({scanner_count}/19 scanners)"""

    if technical_summary:
        card += f"""
\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501
\U0001f4ca TECHNICAL ANALYSIS
{technical_summary}"""

    if fundamental_screen:
        moat = fundamental_screen.get("moat", "N/A")
        conviction = fundamental_screen.get("conviction", "N/A")
        thesis = fundamental_screen.get("thesis", "")
        bull_target = fundamental_screen.get("bull_target", 0)
        bear_target = fundamental_screen.get("bear_target", 0)
        card += f"""
\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501
\U0001f3e6 FUNDAMENTAL SCREEN
Moat: {moat} | Conviction: {conviction}
Bull: \u20b9{bull_target:,.0f} | Bear: \u20b9{bear_target:,.0f}
{thesis}"""

    if boosts:
        card += f"""
\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501
\u26a1 Boosts: {', '.join(boosts)}"""

    confidence_emoji = "\U0001f7e2" if ai_confidence >= 70 else ("\U0001f7e1" if ai_confidence >= 50 else "\U0001f534")
    confidence_label = "HIGH" if ai_confidence >= 70 else ("MEDIUM" if ai_confidence >= 50 else "LOW")

    card += f"""
\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501
{confidence_emoji} AI Confidence: {ai_confidence}% \u2014 {confidence_label}
{ai_reasoning}
\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501
Auto-logged \u00b7 MKUMARAN TRACKER \u00b7 #{signal_id:03d}"""

    return card


def format_short_signal(
    signal_id: int,
    ticker: str,
    company_name: str,
    entry_price: Numeric,
    stop_loss: Numeric,
    target: Numeric,
    rrr: Numeric,
    qty: int,
    risk_amt: Numeric,
    pattern: str,
    ai_confidence: int,
    ai_reasoning: str,
    mwa_direction: str,
    scanner_count: int,
    tv_confirmed: bool,
    tier: int,
    source: str,
    technical_summary: str = "",
    boosts: list[str] | None = None,
) -> str:
    """Format a SHORT signal card for Telegram."""
    entry_price = to_money(entry_price)
    stop_loss = to_money(stop_loss)
    target = to_money(target)
    risk_amt = to_money(risk_amt)
    tv_badge = " \u00b7 TV CONFIRMED" if tv_confirmed else ""
    total_cost = qty * entry_price
    downside_pct = round((entry_price - target) / entry_price * 100, 1)

    card = f"""\U0001f534 SHORT SIGNAL \u2014 SWING TRADE{tv_badge}
Tier {tier} \u00b7 {source} \u00b7 #{signal_id:03d}
\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501
Stock   : {company_name} \u00b7 {ticker}
Entry   : \u20b9{entry_price:,.2f}
Target  : \u20b9{target:,.2f} \u00b7 (-{downside_pct}%) \U0001f3af
SL      : \u20b9{stop_loss:,.2f}
RRR     : {rrr:.1f}:1 \u00b7 RRMS APPROVED \u2705
Qty     : {qty} shares \u00b7 \u20b9{total_cost:,.0f} \u00b7 Risk: \u20b9{risk_amt:,.0f}
Pattern : {pattern}
\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501
MWA     : {mwa_direction} ({scanner_count}/19 scanners)"""

    if technical_summary:
        card += f"""
\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501
\U0001f4ca {technical_summary}"""

    confidence_emoji = "\U0001f7e2" if ai_confidence >= 70 else ("\U0001f7e1" if ai_confidence >= 50 else "\U0001f534")
    confidence_label = "HIGH" if ai_confidence >= 70 else ("MEDIUM" if ai_confidence >= 50 else "LOW")

    card += f"""
\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501
{confidence_emoji} AI Confidence: {ai_confidence}% \u2014 {confidence_label}
{ai_reasoning}"""

    return card


def format_fo_signal(
    verdict: str,
    components: dict[str, str],
    details: dict,
) -> str:
    """Format F&O signal card for Telegram."""
    emoji = "\U0001f7e2" if "BULL" in verdict else ("\U0001f534" if "BEAR" in verdict else "\U0001f535")

    lines = [f"{emoji} F&O SIGNAL \u2014 {verdict}"]
    lines.append("\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501")

    for comp_name, signal in components.items():
        comp_emoji = "\U0001f7e2" if signal in ("BULLISH", "BUY") else ("\U0001f534" if signal in ("BEARISH", "SELL") else "\u26aa")
        lines.append(f"{comp_emoji} {comp_name}: {signal}")

    lines.append("\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501")
    lines.append(f"Verdict: {verdict}")

    return "\n".join(lines)


def format_alert(
    alert_type: str,
    ticker: str,
    cmp: Numeric,
    details: dict,
) -> str:
    """Format alert messages (entry zone, target hit, SL hit, deteriorating).

    `cmp` accepted as Numeric so callers can forward Decimal LTP values
    straight from the money zone. `details` dict values are formatted in
    place via f-string specifiers that handle both Decimal and float.
    """
    cmp = to_money(cmp)
    if alert_type == "ENTRY_ZONE":
        return f"""\u26a1 ENTRY ZONE ALERT \u2014 {ticker}
CMP: \u20b9{cmp:,.2f} \u00b7 Within 2% of LTRP \u20b9{details.get('ltrp', 0):,.2f}
RRR: {details.get('rrr', 0):.1f}:1 \u00b7 Qty: {details.get('qty', 0)}
ACTION: Consider BUY"""

    elif alert_type == "TARGET_HIT":
        return f"""\U0001f3af TARGET HIT \u2014 {ticker}
CMP: \u20b9{cmp:,.2f} \u00b7 Target: \u20b9{details.get('target', 0):,.2f}
P&L: {details.get('pnl_pct', 0):+.1f}%
ACTION: BOOK PROFIT \u2705"""

    elif alert_type == "STOPLOSS_HIT":
        return f"""\U0001f6d1 STOP LOSS HIT \u2014 {ticker}
CMP: \u20b9{cmp:,.2f} \u00b7 SL: \u20b9{details.get('stop_loss', 0):,.2f}
P&L: {details.get('pnl_pct', 0):+.1f}%
ACTION: EXIT POSITION"""

    elif alert_type == "DETERIORATING":
        return f"""\u26a0\ufe0f DETERIORATING \u2014 {ticker}
CMP: \u20b9{cmp:,.2f}
PRRR: {details.get('prrr', 0):.1f} \u2192 CRRR: {details.get('crrr', 0):.1f}
ACTION: Review position"""

    elif alert_type == "RESISTANCE_BREAK":
        return f"""\U0001f680 RESISTANCE BREAK \u2014 {ticker}
CMP: \u20b9{cmp:,.2f} > Pivot \u20b9{details.get('pivot_high', 0):,.2f}
ACTION: Monitor for new highs"""

    elif alert_type == "SUPPORT_BREAK":
        return f"""\U0001f4c9 SUPPORT BREAK \u2014 {ticker}
CMP: \u20b9{cmp:,.2f} < LTRP \u20b9{details.get('ltrp', 0):,.2f}
ACTION: Review stop loss"""

    return f"\U0001f514 ALERT: {alert_type} \u2014 {ticker} @ \u20b9{cmp:,.2f}"


def format_mwa_briefing(
    mwa_score: dict,
    fii_data: dict,
    promoted_stocks: list[str],
) -> str:
    """Format morning MWA briefing for Telegram."""
    direction = mwa_score.get("direction", "N/A")
    bull_pct = mwa_score.get("bull_pct", 0)
    bear_pct = mwa_score.get("bear_pct", 0)

    emoji = "\U0001f7e2" if "BULL" in direction else ("\U0001f534" if "BEAR" in direction else "\U0001f535")

    fii_net = fii_data.get("fii_net", 0)
    dii_net = fii_data.get("dii_net", 0)
    fii_emoji = "\U0001f7e2" if fii_net > 0 else "\U0001f534"

    card = f"""{emoji} MORNING MWA BRIEFING
\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501
Direction : {direction}
Bull      : {bull_pct:.0f}% | Bear: {bear_pct:.0f}%
\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501
{fii_emoji} FII Net: \u20b9{fii_net:,.0f} Cr
\U0001f535 DII Net: \u20b9{dii_net:,.0f} Cr"""

    if promoted_stocks:
        card += f"""
\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501
\U0001f4e4 Auto-promoted: {', '.join(promoted_stocks[:10])}"""

    return card
