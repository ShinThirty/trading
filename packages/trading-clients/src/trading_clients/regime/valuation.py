"""Equity-risk-premium valuation regime classifier."""


def classify_erp(erp_bps: float | None) -> tuple[str, str]:
    """Classify the S&P 500 equity risk premium tier.

    ERP = forward earnings yield − 10Y Treasury yield. Determines how much
    equities compensate over risk-free for the volatility you take, and
    therefore the rate at which earnings translate into multiples.

    Tiers (contrarian / forward-return reading):
    - Generous: ERP >= +500 bps. Equities cheap vs bonds (post-GFC 2010-19 norm).
    - Fair: +200 ≤ ERP < +500 bps. Long-run historical middle.
    - Tight: 0 ≤ ERP < +200 bps. Late-cycle valuation regime.
    - Compressed: -100 ≤ ERP < 0 bps. Equities priced richer than bonds —
      returns come from earnings only, no room for multiple expansion.
    - Compressed-Negative: ERP < -100 bps. Dot-com-bubble territory; any
      rate or earnings shock compresses multiples mechanically.

    Returns (label, detail_string).
    """
    if erp_bps is None:
        return "Unknown", "ERP data unavailable"
    detail = f"ERP {erp_bps:+.0f} bps"
    if erp_bps >= 500:
        return "Generous", detail
    if erp_bps >= 200:
        return "Fair", detail
    if erp_bps >= 0:
        return "Tight", detail
    if erp_bps >= -100:
        return "Compressed", detail
    return "Compressed-Negative", detail
