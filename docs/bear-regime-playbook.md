# Bear Regime Playbook

A decision checkpoint — not an auto-derisk trigger. `get_bear_regime_score` returns a 0-10 composite across 9 dimensions (curve, ERP, credit, positioning, sentiment, vol, technicals, breadth, dealer flow). This doc maps the score's tier to concrete portfolio actions and per-position evaluation rules.

The score is the macro read. **Action templates require cross-referencing actual positions** — that lives in the `/briefing` and `/review` skills, not in the tool itself.

## What the score is and isn't

Historical bears (2000, 2007-08, 2020, 2022) each had different precursor patterns. No single composite reliably fires across all of them — the value is forcing position-level review at threshold crossings, not auto-derisking on threshold breach.

The score will produce **false positives** (firing in late 2015, late 2018, mid-2019, most of 2022-23 without a 2000/2008-magnitude bear). Treat threshold crossings as a *decision checkpoint*, not a sell signal.

The score will produce **false negatives** at exotic patterns the dimensions don't capture (a 1987-style derivatives-driven crash, a 1998-style EM cascade, a black-swan geopolitical event). Don't substitute the score for situational awareness on active overhangs already in memory.

## Tier definitions

| Tier | Score | Default posture | Position cross-ref required |
|---|---|---|---|
| **Clear** | 0-1.99 | Normal accumulation. No special action. | No |
| **Watchful** | 2-3.99 | Verify hedge sized. Prefer CCs on extended winners. | Lightweight (check overlaps with firing dims only) |
| **Building** | 4-5.99 | Pause new entries in high-multiple names. Check CC coverage. | Full scan |
| **Defensive** | 6-7.99 | Trim high-multiple. Raise tail hedge delta. Write CCs on winners. | Full scan + concrete trim list |
| **Crisis** | 8-10 | Freeze new entries. Max tail hedge. Sell rallies. | Full scan + reduce-gross plan |

Tier transitions matter as much as absolute level. A move from Watchful to Building inside a week (driven by 2+ new dimensions flipping to Warning) is the actionable event — the score crossing 4.0 alone, when it has been hovering at 3.8 for a month, is not.

## Per-tier action templates

Actions compound: each tier inherits the prior tier's actions.

### Clear (0-1.99)

- No actions triggered by score
- Normal accumulation per pipeline framework
- Skip the bear regime section in the briefing summary

### Watchful (2-3.99)

- Run `/hedge` if not already done this month — confirm tail hedge is sized appropriately for current portfolio NAV
- For winners >30% from cost with no CC overlay: surface as CC candidates per the 30-45 DTE rule in `covered-call-overlay.md`
- Do **not** trim or exit on score alone

### Building (4-5.99)

All Watchful actions, plus:

- For positions with P/S > 12 OR PEG > 3 (the high-multiple cohort): **pause additional accumulation**. Existing CSPs are fine to keep; don't open new ones in this cohort.
- For positions extended (above 50d SMA AND RSI > 70): surface as aggressive-CC candidates (30 DTE, 0.20-0.25Δ)
- For new pipeline entries (any intent): prefer credit spreads over direct buy / long calls. Lower vega exposure.
- Re-check `get_valuation_regime` — if ERP also compressed, the Building tier signal is reinforced

### Defensive (6-7.99)

All Building actions, plus:

- For positions with P/S > 12 OR PEG > 3 AND >30% from cost: **trim 25-50% on bounces** (not at lows). Lock in gains while macro is still constructive enough for buyers to absorb the trim.
- Run `/hedge` Trigger 1 (maintenance roll candidate) regardless of put delta — increase tail hedge delta proactively
- Write CCs on all extended winners (above 50d SMA + 30%+ gain), not just RSI > 70
- Freeze new accumulate entries; harvest premium only via wheel accounts
- For any position >15% portfolio concentration: surface as oversized; consider trim

### Crisis (8-10)

All Defensive actions, plus:

- **Freeze all new entries**, including at-discount CSPs
- Run `/hedge` Trigger 2 (harvest tranche) per playbook — vol Crisis is the gate
- Convert ATM CCs to deeper ITM (lock in more downside protection)
- Sell rallies in uncovered positions — every counter-trend bounce is an exit opportunity, not a re-entry
- Reduce gross exposure to the structural-hedge program's defensive cash target

## Per-position evaluation rules

When tier ≥ Building, the skill loops over `get_portfolio_summary` positions and applies these rules. The rules use *existing* fundamentals tools — no new MCP infrastructure needed.

| Position attribute | Tool to fetch | Tier-gated action |
|---|---|---|
| Cost basis P&L | `get_portfolio_summary` | Building+: flag winners >30% no-CC. Defensive+: flag winners >30% in high-multiple cohort as trim candidates. |
| P/S ratio | `get_basic_financials` or `get_key_metrics` | Building+: P/S >12 pauses accumulation. Defensive+: P/S >12 + winner = trim candidate. |
| PEG ratio | `get_key_metrics` | Building+: PEG >3 pauses accumulation. Defensive+: PEG >3 + winner = trim candidate. |
| RSI | `get_technical_indicators` | Building+: RSI >70 + above 50d = aggressive CC candidate. |
| Distance from 50d SMA | `get_technical_indicators` | Defensive+: any position above 50d + 30%+ gain = CC candidate. |
| Portfolio concentration | `get_portfolio_summary` | Defensive+: >15% in single name = oversized flag. |
| Existing CC overlay | `get_account_positions` | Building+: presence/absence determines CC candidacy. |

The cohort cut is `P/S >12 OR PEG >3` — both metrics matter and either one triggers. The threshold values are calibrated to the current market structure (May 2026); revisit annually.

## How the score interacts with other tools

- **`get_market_regime`** — the dimensional snapshot. Bear regime score is the synthesis. If the regime verdict is `Crash Active` (vol Crisis), the score will be at Crisis tier; if the verdict is `Pre-Crash Watch`, score is typically Defensive+. Cross-validate; divergence means investigate.
- **`get_equity_risk_premium`** — feeds the Valuation dimension. ERP Compressed-Negative → score's Valuation dim fires Risk → contributes 1.0/9 ≈ 1.1 points alone.
- **`get_yield_curve_state`** — feeds the Curve dimension via `classify_curve_regime`. Bear Steepener fires Warning (0.5).
- **`get_dix_gex`** — feeds the Dealer Flow dimension. GEX deeply negative + DIX low = Risk (1.0).
- **`/hedge`** — Crisis tier gates Trigger 2 (harvest tranche). Defensive tier accelerates Trigger 1 (maintenance roll) cadence.
- **`/briefing`** Step 1f — calls the tool daily, surfaces tier, triggers position cross-ref at tier ≥ Building.
- **`/review`** Section 1.2 — biweekly score check + full action review per this playbook.

## When to override

The score is mechanistic. Override when:

- **Active macro overhang in memory contradicts a low score.** A capex collapse thesis or Hormuz disruption thesis that the score doesn't ingest may warrant Defensive-tier action at a Watchful score reading.
- **Single-position thesis deterioration unrelated to macro.** ANET losing AWS or NVDA losing TSMC capacity isn't a macro signal — handle at the position level regardless of score.
- **Recent score whipsaw.** If the score moved Defensive → Watchful → Defensive in 2 weeks, the underlying dimensions are noisy. Wait for one-week persistence before acting on the second crossing.

## Calibration status

v1 weights are educated guesses. Phase 4 progress:
- ✅ SPY vs RSP equal-weight divergence added to `classify_breadth` as a 4th sub-signal — SPY beating RSP by >2.5pp over 20d fires a "megacap concentration" warning. Catches the 2000 / late-2024 pattern that IWM divergence misses. Both `get_market_regime` and `get_bear_regime_score` consume the same classifier.
- ✅ Historical backfill across 2007 H2 / 2018 Q4 / 2020 Q1 / 2022 Q1 — see [bear-regime-backfill.md](bear-regime-backfill.md) for full per-episode walks and calibration findings. Headline: Building tier is the actionable signal (fires within 3 weeks of peak across all 4 episodes, 20-280d lead time to bottom); Defensive fires only in crisis-magnitude events (2008, briefly 2020); Crisis (≥8.0) is effectively unreachable with v1 weights even at 2008 lows; v1 thresholds shipping unchanged.
- ✅ Score trend + last-below-tier lookback in tool output. Headline now reads e.g. `**3.4 / 10 — Watchful** (Δ7d: +0.4 from 3.0, Δ30d: +1.5 from 1.9)` followed by `_Score has been at ≥ Watchful for ≥21 days (last Clear reading: 2026-04-25)._` when tier ≥ Watchful. The trend re-scores the composite at 7d/30d ago using already-fetched historized inputs (no extra network calls); FactSet ERP + CBOE p/c + AAII are current-snapshot and fall to `available=False` at historical points, which the normalized-composite math handles cleanly. Lookback walks back weekly up to 26 weeks.

Tier transitions remain **soft signals** — re-pull `get_market_regime` and `get_equity_risk_premium` to confirm before any irreversible action. The backfill validates that Building+1-week-persistence is the right action trigger; Watchful alone is too whipsawy to act on. Use the new persistence note to validate "is this regime sticky or noise?" — a Watchful reading that has held for ≥14 days is meaningfully different from one that just crossed.

## Companion reads

- [decision-framework.md](decision-framework.md) — Step 2 Read the Signals integration
- [market-regime.md](market-regime.md) — dimensional reads that feed the score
- [valuation-regime.md](valuation-regime.md) — ERP tier mapping
- [tail-hedge-playbook.md](tail-hedge-playbook.md) — Crisis tier gates harvest triggers
- [covered-call-overlay.md](covered-call-overlay.md) — CC overlay rules referenced by tier templates
