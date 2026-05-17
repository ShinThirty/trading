"""Cross-dimensional regime verdict synthesis."""


def synthesize_verdict(
    volatility: str | None,
    trend: str | None,
    breadth: str | None,
    macro: str | None,
    sectors: str | None,
    credit: str | None,
    speed: str | None,
    warnings: set[str],
) -> tuple[str, str]:
    """Synthesize a single regime verdict from dimensional labels + warnings.

    Priority-ordered decision tree — first match wins. Verdict drives portfolio
    sizing and accumulation timing. Only Crash Active gates the structural
    hedge program's Trigger 2 (harvest tranches); other verdicts inform
    position-level decisions, not hedge actions.

    warnings: set of warning identifiers, e.g. {"uninversion_trap", "semi_divergence"}.

    Returns (verdict, evidence_string).
    """
    # 1. Crash Active — volatility Crisis is decisive
    if volatility == "Crisis":
        return "Crash Active", "Volatility = Crisis"

    # 2. Pre-Crash Watch — leading indicators ahead of vol expansion
    if volatility == "Elevated" and (speed == "Fast" or credit == "Widening"):
        triggers: list[str] = []
        if speed == "Fast":
            triggers.append("tape Fast")
        if credit == "Widening":
            triggers.append("credit Widening")
        return "Pre-Crash Watch", f"Vol Elevated + {' + '.join(triggers)}"
    if volatility == "Normal" and speed == "Fast" and credit == "Widening":
        return "Pre-Crash Watch", "Vol Normal but tape Fast + credit Widening"

    # 3. Recovery — vol coming off elevated with broadening + risk-on
    if volatility == "Elevated" and breadth == "Broadening" and sectors == "Risk-On":
        return "Recovery", "Vol Elevated + Broadening breadth + Risk-On"

    # 4. Bear Setup — structural deterioration without vol Crisis
    bear_score = 0
    bear_parts: list[str] = []
    if trend == "Downtrend":
        bear_score += 1
        bear_parts.append("Downtrend")
    if breadth == "Narrowing":
        bear_score += 1
        bear_parts.append("Narrowing")
    if sectors == "Risk-Off":
        bear_score += 1
        bear_parts.append("Risk-Off")
    if "uninversion_trap" in warnings:
        bear_score += 2
        bear_parts.append("un-inversion trap")
    if "semi_divergence" in warnings:
        bear_score += 1
        bear_parts.append("semi divergence")
    if "credit_trap" in warnings:
        bear_score += 1
        bear_parts.append("credit trap")
    if bear_score >= 3:
        return "Bear Setup", f"{' + '.join(bear_parts)} (score {bear_score}/7)"

    # 5. Late Cycle — warnings emerging but trend still up
    late_score = 0
    late_parts: list[str] = []
    if macro == "Inverted":
        late_score += 1
        late_parts.append("Inverted")
    if breadth == "Narrowing":
        late_score += 1
        late_parts.append("Narrowing")
    if sectors in ("Rotation", "Risk-Off"):
        late_score += 1
        late_parts.append(str(sectors))
    if "uninversion_trap" in warnings:
        late_score += 2
        late_parts.append("un-inversion trap")
    if "credit_trap" in warnings:
        late_score += 1
        late_parts.append("credit trap")
    if late_score >= 2 and trend in ("Uptrend", "Sideways"):
        return "Late Cycle", f"{' + '.join(late_parts)} (score {late_score}/6, trend {trend})"

    # 6. Expansion — clean bull
    if trend == "Uptrend" and breadth in ("Healthy", "Broadening") and sectors == "Risk-On":
        return "Expansion", f"Uptrend + {breadth} breadth + Risk-On"

    # 7. Mixed — fallback when signals don't cohere
    return "Mixed", "signals don't cohere"
