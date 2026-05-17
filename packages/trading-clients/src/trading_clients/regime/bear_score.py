"""Bear regime score — composite 0-10 across 9 dimensions.

Each dimension scores 0 / 0.5 / 1 (Safe / Warning / Risk). Composite is
normalized to 0-10 over available dimensions. Score is a *decision
checkpoint* — historical bears (2000, 2008, 2020, 2022) each had
different precursor patterns, so any single score will misfire on the
next one. The value is forcing position-level review at threshold
crossings, not auto-derisking.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class BearScoreComponent:
    """One dimension's contribution to the bear regime score.

    score: 0.0 (Safe), 0.5 (Warning), or 1.0 (Risk).
    available: False when the underlying data source returned nothing —
      missing dimensions are excluded from the composite rather than
      counted as Safe.
    """

    name: str
    score: float
    label: str  # "Safe" | "Warning" | "Risk" | "Unknown"
    detail: str
    available: bool


def score_bear_curve(
    curve_regime_label: str | None,
    uninversion_trap_warning: str | None,
    spread_history: list[float],
) -> BearScoreComponent:
    """Score the yield-curve dimension.

    Risk (1.0): un-inversion trap with maximum-danger flag (curve > 1.0%
        steepening while Fed cuts — historical recession-ignition pattern).
    Warning (0.5): un-inversion watch (curve crossed back to positive
        while Fed cuts), OR sustained deep inversion (any obs < -50bps in
        past ~3 months), OR Bear Steepener (term-premium expansion that
        pressures equity multiples mechanically).
    Safe (0): otherwise.
    """
    if curve_regime_label is None and uninversion_trap_warning is None and not spread_history:
        return BearScoreComponent("Curve", 0.0, "Unknown", "no curve data", False)

    if uninversion_trap_warning and "UN-INVERSION TRAP" in uninversion_trap_warning:
        return BearScoreComponent(
            "Curve",
            1.0,
            "Risk",
            "un-inversion trap (curve steep + Fed cutting — recession-ignition pattern)",
            True,
        )

    if uninversion_trap_warning and "Un-inversion watch" in uninversion_trap_warning:
        return BearScoreComponent(
            "Curve",
            0.5,
            "Warning",
            "un-inversion watch (crossed to positive while Fed cuts — monitor for acceleration)",
            True,
        )

    # Sustained deep inversion in past ~3 months (60 trading days)
    if spread_history and any(v <= -0.5 for v in spread_history[:60]):
        return BearScoreComponent(
            "Curve",
            0.5,
            "Warning",
            "deep inversion in past 3mo (>50bps inverted) — un-inversion risk pending",
            True,
        )

    if curve_regime_label == "Bear Steepener":
        return BearScoreComponent(
            "Curve",
            0.5,
            "Warning",
            "Bear Steepener — term-premium expansion, pressures multiples mechanically",
            True,
        )

    return BearScoreComponent(
        "Curve", 0.0, "Safe", curve_regime_label or "Normal positive slope", True
    )


def score_bear_valuation(erp_bps: float | None) -> BearScoreComponent:
    """Score the equity-risk-premium dimension.

    Risk (1.0): Compressed-Negative (ERP < -100 bps) — dot-com tier.
    Warning (0.5): Compressed (-100 ≤ ERP < 0 bps) — multiples vulnerable
        to any rate or earnings shock.
    Safe (0): Tight or better (ERP ≥ 0 bps).
    """
    if erp_bps is None:
        return BearScoreComponent("Valuation (ERP)", 0.0, "Unknown", "no ERP data", False)
    if erp_bps < -100:
        return BearScoreComponent(
            "Valuation (ERP)",
            1.0,
            "Risk",
            f"Compressed-Negative ({erp_bps:+.0f} bps) — dot-com tier",
            True,
        )
    if erp_bps < 0:
        return BearScoreComponent(
            "Valuation (ERP)",
            0.5,
            "Warning",
            f"Compressed ({erp_bps:+.0f} bps) — multiples vulnerable to shocks",
            True,
        )
    return BearScoreComponent(
        "Valuation (ERP)",
        0.0,
        "Safe",
        f"ERP {erp_bps:+.0f} bps — within normal range",
        True,
    )


def score_bear_credit(
    current_oas: float | None,
    oas_history: list[float],
    credit_trap_warning: str | None,
) -> BearScoreComponent:
    """Score the HY credit-spread dimension.

    Risk (1.0): credit-trap fired (slow >100 bps grind from 1mo low — the
        2007 H2 / 2022 H1 pattern), OR widening + recession-grade absolute
        level (Δ5d > +50 bps AND OAS > 5.0%).
    Warning (0.5): widening (Δ5d > +50 bps), OR elevated absolute (OAS > 4.0%).
    Safe (0): otherwise.

    Levels rather than just deltas matter — absolute OAS > 5% has only
    occurred during recessions or near-recession scares (2008, 2011,
    2015-16, 2020, 2022).
    """
    if current_oas is None or len(oas_history) < 6:
        return BearScoreComponent("Credit (HY OAS)", 0.0, "Unknown", "no credit data", False)

    delta_5d_bps = (current_oas - oas_history[5]) * 100

    if credit_trap_warning:
        return BearScoreComponent(
            "Credit (HY OAS)",
            1.0,
            "Risk",
            f"slow deterioration ({current_oas:.2f}%, grinding from 1mo low)",
            True,
        )
    if delta_5d_bps > 50 and current_oas > 5.0:
        return BearScoreComponent(
            "Credit (HY OAS)",
            1.0,
            "Risk",
            f"widening + recession-grade ({current_oas:.2f}%, Δ5d {delta_5d_bps:+.0f}bps)",
            True,
        )
    if delta_5d_bps > 50:
        return BearScoreComponent(
            "Credit (HY OAS)",
            0.5,
            "Warning",
            f"widening ({current_oas:.2f}%, Δ5d {delta_5d_bps:+.0f}bps)",
            True,
        )
    if current_oas > 4.0:
        return BearScoreComponent(
            "Credit (HY OAS)",
            0.5,
            "Warning",
            f"elevated ({current_oas:.2f}%, no spike yet — but level matters)",
            True,
        )
    return BearScoreComponent(
        "Credit (HY OAS)",
        0.0,
        "Safe",
        f"{current_oas:.2f}% (Δ5d {delta_5d_bps:+.0f}bps)",
        True,
    )


def score_bear_positioning(positioning_label: str | None) -> BearScoreComponent:
    """Score the CFTC positioning dimension (contrarian polarity).

    Risk (1.0): Crowded Long — 2+ contracts at z ≥ 2.0, flush-vulnerable.
    Warning (0.5): Stretched Long — 1+ long extreme.
    Safe (0): Neutral, Mixed, Stretched/Crowded Short (squeeze fuel, not bear).
    """
    if positioning_label is None or positioning_label == "Unknown":
        return BearScoreComponent("Positioning (COT)", 0.0, "Unknown", "no COT data", False)
    if positioning_label == "Crowded Long":
        return BearScoreComponent(
            "Positioning (COT)",
            1.0,
            "Risk",
            "specs heavily long (2+ contracts at z≥2) — flush-vulnerable",
            True,
        )
    if positioning_label == "Stretched Long":
        return BearScoreComponent(
            "Positioning (COT)",
            0.5,
            "Warning",
            "specs long-tilted (1+ long extreme) — contrarian risk building",
            True,
        )
    return BearScoreComponent("Positioning (COT)", 0.0, "Safe", positioning_label, True)


def score_bear_sentiment(sentiment_label: str | None) -> BearScoreComponent:
    """Score the retail/active-manager sentiment dimension (contrarian polarity).

    Risk (1.0): Greedy — all 3 of CBOE p/c, NAAIM, AAII at greedy extremes.
    Warning (0.5): Stretched — 2+ greedy extremes.
    Safe (0): Neutral / Fearful / Capitulation.
    """
    if sentiment_label is None or sentiment_label == "Unknown":
        return BearScoreComponent("Sentiment", 0.0, "Unknown", "no sentiment data", False)
    if sentiment_label == "Greedy":
        return BearScoreComponent(
            "Sentiment",
            1.0,
            "Risk",
            "all 3 sources at greedy extremes — strong contrarian top signal",
            True,
        )
    if sentiment_label == "Stretched":
        return BearScoreComponent(
            "Sentiment", 0.5, "Warning", "2+ greedy extremes — froth building", True
        )
    return BearScoreComponent("Sentiment", 0.0, "Safe", sentiment_label, True)


def score_bear_volatility(
    vix: float | None,
    vix3m: float | None,
    vix_closes: list[float],
) -> BearScoreComponent:
    """Score the VIX dimension.

    Risk (1.0): Crisis — VIX > VIX3M (backwardation) OR VIX ≥ 35.
    Warning (0.5): Elevated (VIX 25-35), OR sustained complacency
        (VIX < 13 with 60d avg < 14 — squeeze risk on any shock).
    Safe (0): Normal (VIX 13-25).

    The complacency tier catches the 2017 / late-2019 / Jan 2018 pattern
    where vol is so suppressed that any shock produces an outsized squeeze.
    """
    if vix is None:
        return BearScoreComponent("Volatility (VIX)", 0.0, "Unknown", "no VIX data", False)

    backwardation = vix3m is not None and vix > vix3m

    if backwardation or vix >= 35:
        bw = f" backwardation vs VIX3M {vix3m:.1f}" if backwardation else ""
        return BearScoreComponent(
            "Volatility (VIX)", 1.0, "Risk", f"Crisis (VIX {vix:.1f}{bw})", True
        )
    if vix >= 25:
        return BearScoreComponent(
            "Volatility (VIX)",
            0.5,
            "Warning",
            f"Elevated (VIX {vix:.1f}) — stress emerging",
            True,
        )

    if vix < 13 and len(vix_closes) >= 60:
        recent = vix_closes[-60:]
        avg_60d = sum(recent) / len(recent)
        if avg_60d < 14:
            return BearScoreComponent(
                "Volatility (VIX)",
                0.5,
                "Warning",
                f"complacency (VIX {vix:.1f}, 60d avg {avg_60d:.1f}) — squeeze risk on shock",
                True,
            )

    return BearScoreComponent("Volatility (VIX)", 0.0, "Safe", f"VIX {vix:.1f}", True)


def score_bear_technicals(
    spy_closes: list[float],
    spy_volumes: list[float],
    rsi: float | None,
    sma200: float | None,
) -> BearScoreComponent:
    """Score the SPY price-action dimension.

    Risk (1.0): SPY below 200-day SMA, OR 5+ distribution days in last 25
        sessions (-0.5%+ closes on volume > previous day — institutional
        selling pattern).
    Warning (0.5): RSI < 40 (oversold tilt without 200d break yet).
    Safe (0): otherwise.

    Distribution-day logic is the IBD pattern: clusters of high-volume down
    days mark institutional distribution even when the index hasn't broken
    its long-term trend yet.
    """
    if not spy_closes or len(spy_closes) < 25 or len(spy_volumes) != len(spy_closes):
        return BearScoreComponent("Technicals (SPY)", 0.0, "Unknown", "no SPY data", False)

    price = spy_closes[-1]

    dist_days = 0
    start = max(1, len(spy_closes) - 25)
    for i in range(start, len(spy_closes)):
        prev_close = spy_closes[i - 1]
        if prev_close <= 0:
            continue
        day_ret = (spy_closes[i] - prev_close) / prev_close
        if day_ret < -0.005 and spy_volumes[i] > spy_volumes[i - 1]:
            dist_days += 1

    if dist_days >= 5:
        return BearScoreComponent(
            "Technicals (SPY)",
            1.0,
            "Risk",
            f"{dist_days} distribution days in last 25 sessions — institutional selling",
            True,
        )

    if sma200 is not None and price < sma200:
        gap_pct = (price - sma200) / sma200 * 100
        return BearScoreComponent(
            "Technicals (SPY)",
            1.0,
            "Risk",
            f"SPY {price:.2f} below 200d SMA {sma200:.2f} ({gap_pct:+.1f}%)",
            True,
        )

    if rsi is not None and rsi < 40:
        return BearScoreComponent(
            "Technicals (SPY)", 0.5, "Warning", f"RSI {rsi:.0f} oversold tilt", True
        )

    rsi_part = f", RSI {rsi:.0f}" if rsi is not None else ""
    return BearScoreComponent(
        "Technicals (SPY)",
        0.0,
        "Safe",
        f"above 200d ({dist_days} dist days/25){rsi_part}",
        True,
    )


def score_bear_dealer_flow(
    current_dix: float | None,
    current_gex: float | None,
    gex_history: list[float],
    dix_low_threshold: float = 0.40,
) -> BearScoreComponent:
    """Score the SqueezeMetrics dealer-flow dimension.

    Risk (1.0): GEX negative AND in bottom decile of 1y history AND DIX
        low (< 0.40) — vol-amplification regime with distribution.
    Warning (0.5): GEX negative OR DIX low (but not both extreme).
    Safe (0): GEX positive AND DIX ≥ 0.40.
    """
    if current_dix is None or current_gex is None:
        return BearScoreComponent(
            "Dealer Flow (DIX/GEX)", 0.0, "Unknown", "no SqueezeMetrics data", False
        )

    gex_negative = current_gex < 0
    dix_low = current_dix < dix_low_threshold

    if gex_negative and dix_low and gex_history:
        sorted_gex = sorted(gex_history)
        decile_idx = max(0, len(sorted_gex) // 10)
        decile_threshold = sorted_gex[decile_idx]
        if current_gex <= decile_threshold:
            return BearScoreComponent(
                "Dealer Flow (DIX/GEX)",
                1.0,
                "Risk",
                f"GEX deeply negative (1y bottom decile) + DIX low ({current_dix:.3f})",
                True,
            )

    if gex_negative or dix_low:
        parts: list[str] = []
        if gex_negative:
            parts.append("GEX negative")
        if dix_low:
            parts.append(f"DIX low ({current_dix:.3f})")
        return BearScoreComponent("Dealer Flow (DIX/GEX)", 0.5, "Warning", " + ".join(parts), True)

    return BearScoreComponent(
        "Dealer Flow (DIX/GEX)",
        0.0,
        "Safe",
        f"DIX {current_dix:.3f}, GEX positive",
        True,
    )


def score_bear_breadth(
    breadth_label: str | None,
    breadth_detail: str | None = None,
) -> BearScoreComponent:
    """Score the market-internals breadth dimension via classify_breadth output.

    Mapping:
        Narrowing  → Risk    (≥2 warnings — small-caps lagging, defensive
                              rotation, megacap concentration, or thin volume)
        Mixed      → Warning (1 warning fires — divergence emerging)
        Healthy / Broadening → Safe

    Reuses the existing breadth classifier (SPY/IWM divergence + XLY/XLU
    rotation + SPY volume trend + optional SPY/RSP equal-weight concentration)
    so the breadth signal is consistent with the market-regime view rather
    than introducing a competing definition.
    """
    if breadth_label is None or breadth_label == "Unknown":
        return BearScoreComponent("Breadth", 0.0, "Unknown", "no breadth data", False)
    if breadth_label == "Narrowing":
        return BearScoreComponent(
            "Breadth",
            1.0,
            "Risk",
            breadth_detail or "≥2 warnings (small-cap/defensive/volume) — index thinning",
            True,
        )
    if breadth_label == "Mixed":
        return BearScoreComponent(
            "Breadth",
            0.5,
            "Warning",
            breadth_detail or "1 divergence warning fires — internals weakening",
            True,
        )
    return BearScoreComponent("Breadth", 0.0, "Safe", breadth_label, True)


def synthesize_bear_regime(
    components: list[BearScoreComponent],
) -> tuple[float, str, list[BearScoreComponent], list[BearScoreComponent]]:
    """Combine per-dimension scores into a composite 0-10 score + tier.

    Composite is normalized over *available* dimensions — missing data is
    excluded from both numerator and denominator. When coverage < 60% the
    tier label is suffixed with "(incomplete data)" so callers can flag
    low-confidence scores.

    Tiers:
        0-1.99  Clear      — no special action
        2-3.99  Watchful   — verify tail hedge, prefer CCs on extended winners
        4-5.99  Building   — pause new entries in high-multiple names
        6-6.99  Defensive  — trim high-multiple, raise tail hedge delta
        7-10    Crisis     — freeze new entries, max tail hedge, sell rallies

    Returns (composite_0_10, tier, top_contributors, missing).
    top_contributors is sorted by score desc, capped at 5, only includes
    components with score > 0.
    """
    available = [c for c in components if c.available]
    missing = [c for c in components if not c.available]

    if not available:
        return 0.0, "Unknown (no data)", [], components

    raw = sum(c.score for c in available)
    max_raw = float(len(available))
    composite = (raw / max_raw) * 10.0

    if composite < 2.0:
        tier = "Clear"
    elif composite < 4.0:
        tier = "Watchful"
    elif composite < 6.0:
        tier = "Building"
    elif composite < 7.0:
        tier = "Defensive"
    else:
        tier = "Crisis"

    coverage = len(available) / len(components)
    if coverage < 0.6:
        tier = f"{tier} (incomplete data — {len(available)}/{len(components)} dimensions)"

    top_contributors = sorted(
        (c for c in available if c.score > 0), key=lambda c: c.score, reverse=True
    )[:5]

    return composite, tier, top_contributors, missing
