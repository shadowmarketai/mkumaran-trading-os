import logging

logger = logging.getLogger(__name__)


def check_auto_reject(
    rrr: float,
    sector_strength: str,
    direction: str,
    fii_net: float,
    volume_scanners: list[str],
    cmp: float,
    ltrp: float,
    ticker: str = "",
) -> tuple[bool, str]:
    """
    Check auto-reject conditions. Returns (rejected, reason).

    Auto-reject if:
    1. RRR < min_rrr (3.0 for equity, 2.0 for MCX/NFO/CDS)
    2. Sector WEAK for longs
    3. FII selling > 2000 Cr for longs
    4. No volume confirmation (scanners 6 AND 7 both absent)
    5. CMP > LTRP * 1.05 (missed entry zone)
    """
    # Asset-class conditional minimum RRR
    min_rrr = 3.0
    if ":" in ticker:
        exchange = ticker.split(":")[0]
        if exchange in ("MCX", "NFO", "CDS"):
            min_rrr = 2.0  # Leverage instruments accept lower RRR
    if rrr < min_rrr:
        return True, f"RRR {rrr:.2f} < minimum {min_rrr:.1f}"

    if direction == "LONG" and sector_strength == "WEAK":
        return True, "Sector is WEAK -- longs blocked"

    if direction == "SHORT" and sector_strength == "STRONG":
        return True, "Sector is STRONG -- shorts blocked"

    if direction == "LONG" and fii_net < -2000:
        return True, f"FII selling {fii_net:.0f} Cr > threshold (2000 Cr)"

    has_vol_avg = "6_vol_above_avg" in volume_scanners
    has_vol_2x = "7_vol_2x" in volume_scanners
    if not has_vol_avg and not has_vol_2x:
        return True, "No volume confirmation (scanners 6 & 7 absent)"

    if direction == "LONG" and ltrp > 0 and cmp > ltrp * 1.05:
        return True, f"CMP {cmp:.2f} > LTRP*1.05 ({ltrp * 1.05:.2f}) -- missed entry zone"

    return False, ""


def validate_entry_rules(
    direction: str,
    scanner_results: dict[str, dict],
    mwa_direction: str,
    sector_strength: str,
) -> tuple[bool, str]:
    """
    Validate optimal combination rules.

    Long: (Scanner 1 OR 12) + Scanner 2 + Scanner 6 + MWA BULL/MILD_BULL + Sector not WEAK
    Short: (Scanner 3 OR 13) + Scanner 4 + Scanner 6 + MWA BEAR/MILD_BEAR + Sector not STRONG
    """
    active_scanners = {k for k, v in scanner_results.items() if v.get("count", 0) > 0}

    if direction == "LONG":
        has_trend = "1_swing_low" in active_scanners or "12_rsi_above_30" in active_scanners
        has_upswing = "2_upswing" in active_scanners
        has_volume = "6_vol_above_avg" in active_scanners
        has_mwa = mwa_direction in ("BULL", "MILD_BULL")
        has_sector = sector_strength != "WEAK"

        if not has_trend:
            return False, "Missing trend scanner (1 or 12)"
        if not has_upswing:
            return False, "Missing upswing scanner (2)"
        if not has_volume:
            return False, "Missing volume scanner (6)"
        if not has_mwa:
            return False, f"MWA direction {mwa_direction} not bullish"
        if not has_sector:
            return False, "Sector is WEAK"

        return True, "All long entry rules satisfied"

    elif direction == "SHORT":
        has_trend = "3_swing_high" in active_scanners or "13_rsi_below_70" in active_scanners
        has_downswing = "4_downswing" in active_scanners
        has_volume = "6_vol_above_avg" in active_scanners
        has_mwa = mwa_direction in ("BEAR", "MILD_BEAR")
        has_sector = sector_strength != "STRONG"

        if not has_trend:
            return False, "Missing trend scanner (3 or 13)"
        if not has_downswing:
            return False, "Missing downswing scanner (4)"
        if not has_volume:
            return False, "Missing volume scanner (6)"
        if not has_mwa:
            return False, f"MWA direction {mwa_direction} not bearish"
        if not has_sector:
            return False, "Sector is STRONG"

        return True, "All short entry rules satisfied"

    return False, f"Invalid direction: {direction}"


def apply_confidence_boosts(
    base_confidence: int,
    scanner_results: dict[str, dict],
    tv_confirmed: bool,
    delivery_pct: float,
    fii_net: float,
    sector_strength: str,
    direction: str,
) -> tuple[int, list[str]]:
    """
    Apply confidence boost multipliers.

    Returns (final_confidence, list of boost reasons)
    """
    confidence = base_confidence
    boosts: list[str] = []
    active_scanners = {k for k, v in scanner_results.items() if v.get("count", 0) > 0}

    # Supertrend +15%
    if "17_supertrend" in active_scanners:
        confidence += 15
        boosts.append("Supertrend +15%")

    # 52-week high +15%
    if "19_52week_high" in active_scanners:
        confidence += 15
        boosts.append("52-wk High +15%")

    # Volume 2x +10%
    if "7_vol_2x" in active_scanners:
        confidence += 10
        boosts.append("Volume 2x +10%")

    # Sector STRONG (longs) or WEAK (shorts) +10%
    if (direction == "LONG" and sector_strength == "STRONG") or \
       (direction == "SHORT" and sector_strength == "WEAK"):
        confidence += 10
        boosts.append(f"Sector {sector_strength} +10%")

    # FII net buying +10%
    if direction == "LONG" and fii_net > 0:
        confidence += 10
        boosts.append("FII buying +10%")

    # TradingView confirmed +10%
    if tv_confirmed:
        confidence += 10
        boosts.append("TV confirmed +10%")

    # Delivery > 60% +10%
    if delivery_pct > 60:
        confidence += 10
        boosts.append(f"Delivery {delivery_pct:.0f}% +10%")

    # MACD bullish +8%
    if "18_macd" in active_scanners:
        confidence += 8
        boosts.append("MACD +8%")

    # 3+ scanners match +5% per extra
    bull_active = len(active_scanners.intersection({"1_swing_low", "2_upswing", "6_vol_above_avg",
                                                      "10_50day_high", "17_supertrend", "18_macd", "19_52week_high"}))
    if bull_active >= 3:
        extra_boost = (bull_active - 2) * 5
        confidence += extra_boost
        boosts.append(f"{bull_active} scanners +{extra_boost}%")

    # Cap total boost at 25% above base to prevent over-confidence
    max_boost = 25
    total_boost = confidence - base_confidence
    if total_boost > max_boost:
        confidence = base_confidence + max_boost
        boosts.append(f"Boost capped at +{max_boost}%")

    # Cap at 100
    confidence = min(confidence, 100)

    logger.info("Confidence: %d -> %d (%d boosts)", base_confidence, confidence, len(boosts))

    return confidence, boosts
