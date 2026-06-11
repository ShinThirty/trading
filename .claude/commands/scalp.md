---
description: Intraday SPY/QQQ options scalp workflow — pre-session prep (regime + daily bias + level map + discipline checklist) and post-session trade-grading review. Built to enforce discipline, not to generate more setups.
arguments:
  - name: symbol
    description: Ticker — SPY or QQQ only. Defaults to QQQ if omitted.
    required: false
  - name: mode
    description: Sub-mode — omit for default (pre-session prep); or `review` (post-session order grading) / `check` (thin live snapshot)
    required: false
---

Intraday scalp workflow for **$ARGUMENTS.symbol** (default QQQ), mode **$ARGUMENTS.mode** (default: pre-session prep).

## Role and guardrails — read first

This skill supports **intraday 0–1DTE option scalping** on the index ETFs. Its purpose is to **enforce discipline**, not to manufacture setups. The lesson that created it (see memory `project-qqq-scalping`): the *reads* are usually fine — good losses come from no stops, chasing, and trading the middle. So this skill leans on the side of *fewer, cleaner trades*, and every mode ends in a discipline artifact, not a trade signal.

Five guardrails apply to every mode:

1. **Discipline over analysis.** Pre-session output ALWAYS ends with the discipline checklist; review ALWAYS grades stop-honor and win/loss size-asymmetry first. More setups ≠ better. If the day has no clean edge, the correct output is "no-trade conditions — sit out."
2. **Data limits — be honest about them.** `get_technical_indicators` is **daily-only** (no intraday bars from any tool). The real scalper's edge — Level 2 / order flow / tape speed — is **not in this toolset**; it's on the Webull screen. This skill is **prep + review + lagging context**, NOT the live execution surface. Never pretend to out-speed the user's chart.
3. **Never green-light a click.** Produce the map, the levels, and the rules. The user pulls the trigger. Do not encourage more trading; if anything, bias toward "wait."
4. **SPY/QQQ only.** These have the penny-wide spreads + daily expirations that make option scalping viable. If `$ARGUMENTS.symbol` is anything else, refuse: *"Scalp skill is SPY/QQQ-only — single-name option spreads + thinner expiries break the scalp math. Use /ta for single-name intraday levels."*
5. **Account = Webull "Individual Cash."** Scalping lives there (per memory). Review mode resolves it via `get_app_subscriptions` and defaults to the `Individual Cash` account — never hardcode the ID.

Parse `$ARGUMENTS.mode`: empty → `prep` (default). Valid: `prep`, `review`, `check`.

---

## Mode `prep` — pre-session setup (the Step A sheet)

Run this before the open (or early in the session). One command that produces the day's map + the rules.

**Step 0 — clock.** Call `get_market_clock`. If pre-market, VWAP/timesales have no current-session data → build levels from the **prior** session (note it). If open, use live data.

**Step 1 — regime (the day-type filter).** Call `get_dix_gex`. Read GEX sign + **1-month percentile**, and translate to a scalp playbook:
- **Positive GEX, high percentile** → strong dealer pin. Range/mean-revert day: fade the edges back to VWAP, dip-buys reliable.
- **Positive GEX, LOW percentile (≤~10)** → suppression is *thinning*. Still a pin, but **fragile** — a volume break can extend and round-trip the fade. Flag this explicitly; it's the trap.
- **Negative GEX** → trend/momentum day. Go *with* breakouts; do not fade.
- Note DIX (accumulation vs distribution) and any divergence flag as background, not a same-day trigger.

**Step 2 — daily bias (a weak prior, not a verdict).** Call `get_technical_indicators` (daily). Read **ADX** (>25 = real trend, <20 = chop/no-trend), **+DI/-DI** direction, price vs **SMA20/SMA50**, **MACD**. Output one line: "which direction am I *allowed* to scalp, and is it even a trend day." **State the override rule:** the intraday tape (VWAP + structure) overrules this daily bias for a same-day scalp — on a conflict, the tape wins; the daily read just sets the lean.

**Step 3 — level map.** Call `get_quote` (prev close, day H/L, 52w), `get_timesales` (prior or current session, 15min — for intraday structure), and `get_vwap` (if open). Map and state as **price points**:
- Prior-day high / low / close (the primary pivots).
- Overnight / pre-market range; opening-range high/low (once 9:30–9:45 prints).
- Key MAs from Step 2 (SMA50, SMA20), lower/upper Bollinger band.
- Round numbers inside the range.
- VWAP + its slope (once open).
For deeper structural S/R, defer to `/ta $ARGUMENTS.symbol` rather than re-deriving — reuse, don't duplicate.

**Step 4 — fragility check.** Flag anything that weakens the bias: OBV divergence (from Step 2), DIX accumulation-into-weakness, price sitting on a major level (bounce/break risk). If fragile → shrink size, shorten leash.

**Step 5 — the plan.** Output the day's structure tightly:
- **The edges:** support edge ↔ resistance edge (the range you fade inside, or the breakout level you go with).
- **Regime playbook:** pin = fade edges to VWAP; breakout = go-with on the pullback-hold, or stand aside (never fade a volume breakout).
- **Invalidation:** the price that flips the regime (range edge breaking on volume = pin over).
- **Expected range / sizing input:** ATR(14) from Step 2 as % of price → the realistic intraday range; size targets/stops as fractions of it.

**Step 6 — the discipline checklist (ALWAYS print this last, verbatim-style):**

> **Before every click:**
> - [ ] Name the **level + target + stop** out loud. Can't name all three → it's not a trade.
> - [ ] **Hard stop set** (≈ −X per contract). No negotiation, no "it'll come back."
> - [ ] Entry is **at a named edge**, not the middle of the range.
> - [ ] **Not chasing** — entering the pullback-to-level, not the extended move.
> - [ ] Size is **A+-only large**; impulse trades are small or skipped.
> - [ ] In a **trade window** (9:30–10:30 / 3:00–4:00), not the 11:30–2:00 chop.
>
> **Session caps:** max __ trades, daily stop −$__ (ask the user to set both if not already fixed).

---

## Mode `review` — post-session trade grading

The feedback loop on discipline. Run after the close (or when the user says "done").

**Step 1 — resolve account + pull fills.** Call `get_app_subscriptions`, take the `Individual Cash` account ID. Call `get_order_history` for the session.
- **Gotchas (learned the hard way):** `start_date` AND `end_date` are both required and **must differ** — use `[session_date, session_date + 1]`. And Webull **rate-limits parallel calls** — if querying more than one account/range, call **sequentially**, not in one batch.

**Step 2 — reconstruct round-trips.** Filter to the day's scalp underlying (SPY/QQQ) options; set aside prior-day and unrelated fills (note them, don't grade them). Pair BUY/SELL into round-trips, handling partial fills and multi-contract averaging carefully. For each round-trip capture: entry/exit price, contracts, direction.

**Step 3 — grade each round-trip.** Tag every trip:
- **Framework-trade vs leak** — was the entry at a *named edge* consistent with that part of the day's regime (pin fade / breakout-pullback / edge-rejection)? Or was it mid-range / wrong-edge / a chase?
- **Win / loss** — by direction (sell vs buy price). This is a comparison, not a computed ledger.
- **Per-contract magnitude** — for the asymmetry read.

**Step 4 — surface the diagnostics (these, in this order):**
1. **Win/loss SIZE asymmetry** (the #1 killer) — typical winner magnitude vs typical loser magnitude per contract. Losers larger than winners = the whole problem.
2. **Stop-honor** — were losers cut small, or allowed to bleed past where a stop should have been?
3. **Chase count** — entries into already-extended moves.
4. **Middle trades** — entries with no nameable edge.
5. **Size-on-chase** — was the *biggest* size on a *low-quality* entry?
6. **Cancelled-order pattern** — chasing fills / hesitation.
7. **The deliberate-vs-impulse tell** — the framework trades are usually the ones the user could articulate live; the leaks are the impulsive, unmentioned ones.

**Step 5 — do NOT hand-compute precise net P&L.** Tallying across partials/fees is error-prone (per the no-manual-math rule) — the broker's P&L page is authoritative. Surface the **pattern**, not a certified dollar ledger. Magnitudes per contract are fine to illustrate the asymmetry lesson.

**Step 6 — output:** the round-trip table (framework vs leak, win/loss), the 3 sharpest diagnostics, and 1–3 ranked fixes. If a discipline pattern persists or improves across sessions, update memory `project-qqq-scalping` so the trend is tracked.

---

## Mode `check` — thin live snapshot (use sparingly)

A quick "where are we" relative to the prep map. **This is lagging context — the Webull chart + L2 is the real-time surface. Do not use this to chase.**

Call `get_quote` + `get_vwap` + `get_timesales` (last ~10 1-min bars) for `$ARGUMENTS.symbol`. Output 3 lines max:
- **Price vs VWAP** (side + slope) and distance to the nearest mapped edge.
- **Recent volume** behavior (expanding into a move = real; fading = suspect).
- **One verdict:** *"at an edge — here's the setup (level/target/stop)"* OR *"middle of range — no trade"* OR *"trigger fired: [what]."*

Never expand `check` into a trade recommendation beyond naming the setup at an edge. If price is mid-range, the only correct answer is "no trade, wait."

---

*v1. If scalping matures across sessions, extract the framework + regime playbook into `docs/scalping-playbook.md` and reference it here (the way `/ta` references its playbooks), rather than growing this file.*
