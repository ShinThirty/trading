"""Fed policy classifier (per-meeting) + path-aware synthesis."""

# Month order for sorting "January Meeting", "February Meeting", … labels
# used by Polymarket's `fed-rate-hike-by-...?` / `fed-rate-cut-by-...?` events.
_MONTH_ORDER = {
    m: i
    for i, m in enumerate(
        [
            "january", "february", "march", "april", "may", "june",
            "july", "august", "september", "october", "november", "december",
        ],
        start=1,
    )
}


def _meeting_sort_key(label: str) -> int:
    word = label.lower().split(" ", 1)[0]
    return _MONTH_ORDER.get(word, 99)


def classify_policy(
    outcomes: list[tuple[str, float]],
    hold_threshold: float = 0.70,
    move_threshold: float = 0.50,
    bias_threshold: float = 0.25,
) -> tuple[str, str]:
    """Classify what the prediction market has priced in for the next FOMC.

    Polymarket FOMC events expose binary YES/NO contracts on each possible
    decision: "No change", "25 bps decrease", "50+ bps decrease", "25 bps
    increase", "50+ bps increase". The yes-price on each is the implied
    probability. We bucket those into hold / cut / hike and label the
    consensus tilt.

    outcomes: list of (label, implied_prob) from a Polymarket FOMC event.
        Labels are matched case-insensitively for "no change", "decrease",
        "increase". Anything that doesn't match is ignored.
    hold_threshold: P(hold) above this → "Hold Priced"
    move_threshold: P(cut) or P(hike) above this → "Cut/Hike Priced"
    bias_threshold: minimum spread between cut and hike before declaring a bias

    Six-tier output:
      - Hold Priced — high consensus on no change (low surprise risk on direction)
      - Cut Priced — easing already priced (hawk surprise = downside)
      - Hike Priced — tightening already priced (dove surprise = upside)
      - Cut Bias — leaning dovish but not consensus
      - Hike Bias — leaning hawkish but not consensus
      - Uncertain — split, no clear lean

    Returns (label, detail_string).
    """
    if not outcomes:
        return "Unknown", "no FOMC market available"

    p_hold = 0.0
    p_cut = 0.0
    p_hike = 0.0
    matched = 0
    for label, prob in outcomes:
        s = label.lower().strip()
        if "no change" in s or s in {"hold", "unchanged"}:
            p_hold += prob
            matched += 1
        elif "decrease" in s or "cut" in s:
            p_cut += prob
            matched += 1
        elif "increase" in s or "hike" in s:
            p_hike += prob
            matched += 1

    if matched == 0:
        return "Unknown", "no recognized FOMC outcome labels"

    detail = f"hold {p_hold * 100:.0f}% / cut {p_cut * 100:.0f}% / hike {p_hike * 100:.0f}%"

    if p_hold >= hold_threshold:
        return "Hold Priced", detail
    if p_cut >= move_threshold:
        return "Cut Priced", detail
    if p_hike >= move_threshold:
        return "Hike Priced", detail
    if p_cut - p_hike >= bias_threshold:
        return "Cut Bias", detail
    if p_hike - p_cut >= bias_threshold:
        return "Hike Bias", detail
    return "Uncertain", detail


def synthesize_policy_path(
    next_fomc_outcomes: list[tuple[str, float]] | None,
    hike_by_outcomes: list[tuple[str, float]] | None,
    cut_by_outcomes: list[tuple[str, float]] | None,
    year_end_outcomes: list[tuple[str, float]] | None,
    *,
    tail_threshold: float = 0.10,
) -> tuple[str, str]:
    """Path-aware Fed policy classifier — extends classify_policy with the
    cumulative-by-meeting path and the year-end rate distribution.

    Polymarket exposes three useful event classes under the `fed` tag:

      1. **Fed Decision in <month>?** — per-meeting hold / cut / hike (the
         input to classify_policy).
      2. **Fed rate hike by ...?** / **Fed rate cut by ...?** — cumulative
         binary YES on a hike/cut having occurred by each calendar meeting.
         Child labels are "June Meeting", "September Meeting", etc.
      3. **What will the Fed rate be at the end of <year>?** — distribution
         across discrete rate buckets (e.g. "3.5%", "3.75%", "4.0%").

    Synthesis: the *headline* label is the next-meeting classification
    (e.g. "Hold Priced") with a **tail qualifier** when the cumulative
    path or year-end distribution leans materially in one direction:

      - "Hold Priced — Hawkish Tail"    — P(hike-by-last) - P(cut-by-last) >= tail_threshold
                                          OR year-end mode is above current
      - "Hold Priced — Dovish Tail"     — P(cut-by-last) - P(hike-by-last) >= tail_threshold
                                          OR year-end mode is below current
      - "Hold Priced — Balanced Tails"  — both rails meaningful but neither dominates
      - "Hold Priced"                   — tail rails too thin to call

    "Cut Priced" / "Hike Priced" / "Cut Bias" / "Hike Bias" are returned
    without a tail qualifier — if the next meeting itself is already
    pricing a move, the tail discussion is redundant.

    All inputs are optional: when only next_fomc_outcomes is given, falls
    back to classify_policy and returns its label/detail unchanged. This
    keeps the function a strict superset and tolerates gaps in Polymarket
    coverage (e.g. months when the hike-by event hasn't been listed yet).

    Returns (label, detail). The detail string is compact — meant to fit
    on one regime-table row.
    """
    if not next_fomc_outcomes:
        return classify_policy([])

    label, next_detail = classify_policy(next_fomc_outcomes)

    # Extract the latest (chronologically) cumulative-path data point for
    # each side. Polymarket lists past months too (with 0% if resolved
    # negatively); we want the rightmost meeting on each rail.
    def _latest(outcomes: list[tuple[str, float]] | None) -> tuple[str, float] | None:
        if not outcomes:
            return None
        return max(outcomes, key=lambda x: _meeting_sort_key(x[0]))

    last_hike = _latest(hike_by_outcomes)
    last_cut = _latest(cut_by_outcomes)

    # Year-end mode: pick the highest-probability bucket. Whether it's above
    # or below the *current* implied rate is a contextual judgment we leave
    # to the caller — we just surface the mode in the detail string. Comparing
    # to the current rate requires knowing the current rate, which is FRED
    # territory (DFEDTARU) and not in scope for this function.
    year_end_mode = None
    if year_end_outcomes:
        year_end_mode = max(year_end_outcomes, key=lambda x: x[1])

    # Tail qualifier — only meaningful when next meeting is Hold Priced.
    if label == "Hold Priced" and (last_hike or last_cut):
        p_hike_last = last_hike[1] if last_hike else 0.0
        p_cut_last = last_cut[1] if last_cut else 0.0
        # Material tail = at least one side ≥10% AND the spread between
        # them ≥ tail_threshold.
        either_material = max(p_hike_last, p_cut_last) >= 0.10
        if either_material:
            spread = p_hike_last - p_cut_last
            if spread >= tail_threshold:
                label = "Hold Priced — Hawkish Tail"
            elif -spread >= tail_threshold:
                label = "Hold Priced — Dovish Tail"
            else:
                label = "Hold Priced — Balanced Tails"

    # Build compact detail string. When no path data is available, return the
    # bare next-meeting detail (preserves classify_policy() output exactly).
    path_parts: list[str] = []
    if last_hike:
        month = last_hike[0].split()[0][:3]
        path_parts.append(f"hike-by-{month} {last_hike[1] * 100:.0f}%")
    if last_cut:
        month = last_cut[0].split()[0][:3]
        path_parts.append(f"cut-by-{month} {last_cut[1] * 100:.0f}%")
    if year_end_mode:
        path_parts.append(f"YE {year_end_mode[0]} @{year_end_mode[1] * 100:.0f}%")

    if not path_parts:
        return label, next_detail
    return label, " ; ".join([f"next {next_detail}", *path_parts])
