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
2. **Data limits — be honest about them.** `get_technical_indicators` is **daily-only** (no intraday bars from any tool). **Daily signals draw the map and set the lean — they never pull the trigger.** Levels (SMA20/50, Bollinger bands, prior H/L/C), the range envelope (ATR), and the day-type prior (ADX/±DI) are the *right* use; the momentum/participation oscillators (RSI, MACD, **OBV**) describe a **multi-week state** and must never be read as same-session timing or participation. The real scalper's edge — Level 2 / order flow / tape speed — is **not in this toolset**; it's on the Webull screen. This skill is **prep + review + lagging context**, NOT the live execution surface. Never pretend to out-speed the user's chart.
3. **Never green-light a click.** Produce the map, the levels, and the rules. The user pulls the trigger. Do not encourage more trading; if anything, bias toward "wait."
4. **SPY/QQQ only.** These have the penny-wide spreads + daily expirations that make option scalping viable. If `$ARGUMENTS.symbol` is anything else, refuse: *"Scalp skill is SPY/QQQ-only — single-name option spreads + thinner expiries break the scalp math. Use /ta for single-name intraday levels."*
5. **Account = Webull "Individual Cash."** Scalping lives there (per memory). Review mode resolves it via `get_app_subscriptions` and defaults to the `Individual Cash` account — never hardcode the ID.

Parse `$ARGUMENTS.mode`: empty → `prep` (default). Valid: `prep`, `review`, `check`.

---

## Live layer — your screen (Webull Premium)

`/scalp prep` (this skill, via Tradier-backed MCP tools) draws the **map and the lean**. The **live trigger** is not in this toolset — it's on your Webull Premium screen, across four panels. Prep is the skill's job; the click is the screen's. **I can't see any of these live — when price is at an edge, your screen beats `check`.** Read all four **only when price is at a pre-mapped edge** (Step 3); mid-range they're noise. And remember the instrument has to be SPY/QQQ — penny option spreads + 0DTE — for any of this to be tradeable.

**1. Level 2 order book (depth curve + ladder) — "bounce or break at this level?"**
- The book is *resting intentions*, not trades — and displayed size is a **promise, not a commitment** (it can be pulled). Never trust a wall just because it's big. Lit Nasdaq depth only: hidden/iceberg/dark size isn't shown.
- At a mapped edge, the wall does one of three things:
  - **Refreshes** when hit (size reloads) → real absorption → **bounce / fade holds**.
  - **Eaten** — shrinks *with prints going off on the tape* → real demand → **break, go-with**.
  - **Pulled** — vanishes *with no prints* → spoof → **break, but hollow — be careful**.
- Eaten vs pulled is the whole read, and L2 alone can't tell them apart → confirm on the tape.
- **When it's too fast:** widen the price **grouping** (collapses the flicker into fewer fatter levels), watch the **depth curve** (moves slower than the rows), or switch your primary read to the tape.

**2. Time & Sales — the tape — "is the move real?"**
- Executed prints (reality) vs L2's intentions. The **lie-detector** for the book.
- **Filter to size** (e.g. ≥100) — kill the 1–50-lot router spray; read only prints that matter.
- **Color = aggressor:** green = buyer lifted the offer; red = seller hit the bid; neutral = mid/hidden. Read the *balance of color*, not just that trades happened. (The side tag is an inference from price-vs-quote — shaky when the quote's moving fast.)
- **Sweeps:** a burst of same-instant prints across several prices = **one** aggressive order, not many traders — don't overcount.
- **Speed:** accelerating prints = momentum; *unreadably* fast = the burst itself → **not your entry, wait for the pullback** where it slows enough to read.

**3. NOII (Net Order Imbalance Indicator) — auction lean — open & close windows only**
- Live only in the cross windows: **~9:28–9:30 (Opening Cross)** and **~3:50–4:00 (Closing Cross)** — i.e. inside your two trade windows.
- **Imbalance Side** = which side has unpaired MOC/LOC interest. **Near / Far** indicative prices *above* Reference = the cross is leaning **up**; *below* = leaning **down**. Low **Price Variance** (<1%) = stable, trustworthy indication.
- Use as a **directional lean into the print** (persistent buy imbalance + rising indicatives = MOC buying pinning up into 4:00).
- **Caveat:** it can flip in the final seconds as offsetting orders land. A *lean*, not a lock.

**4. Vol Analysis (volume-at-price) — the level-map input**
- Volume traded *at each price*, split buy/sell. **High-volume nodes (HVNs) are S/R magnets** — a stronger level than a round number, because real size changed hands there. Feed them into the Step 3 map.
- The **buy/sell split** shows who controlled each shelf (heavy sell node = where sellers capitulated; heavy buy node = where buyers absorbed — e.g. a closing-cross buy print).
- **Purely descriptive** — it confirms where levels *are*, it does not predict the next move.

**The handoff:** prep hands you the edges; **L2 + tape confirm bounce-vs-break at the edge**, **NOII gives the auction lean** in the open/close windows, **Vol Analysis sharpens where the edges are**. The stop and the edge-discipline still do the real work — these confirm a trade at a pre-mapped level, they never manufacture one.

---

## Mode `prep` — pre-session setup (the Step A sheet)

Run this before the open (or early in the session). One command that produces the day's map + the rules.

**Step 0 — clock.** Call `get_market_clock`. If pre-market, VWAP/timesales have no current-session data → build levels from the **prior** session (note it). If open, use live data.

**Step 1 — regime (the day-type filter).** Call `get_dix_gex`. Read GEX sign + **1-month percentile**, and translate to a scalp playbook:
- **Positive GEX, high percentile** → strong dealer pin. Range/mean-revert day: fade the edges back to VWAP, dip-buys reliable.
- **Positive GEX, LOW percentile (≤~10)** → suppression is *thinning*. Still a pin, but **fragile** — a volume break can extend and round-trip the fade. Flag this explicitly; it's the trap.
- **Negative GEX** → trend/momentum day. Go *with* breakouts; do not fade.
- Note DIX (accumulation vs distribution) and any divergence flag as background, not a same-day trigger.

**Step 2 — daily bias (a weak prior, not a verdict).** Call `get_technical_indicators` (daily). Use it for **levels + day-type only**: **ADX** (>25 = real trend, <20 = chop/no-trend) and **+DI/-DI** set whether it's even a trend day and which way; price vs **SMA20/SMA50** + Bollinger bands are *levels* feeding Step 3; **ATR** is the range envelope for Step 5. **RSI / MACD / OBV here are multi-week state — they color the lean and the fragility check, never an intraday entry.** Output one line: "which direction am I *allowed* to scalp, and is it even a trend day." **State the override rule:** the intraday tape (VWAP + structure) overrules this daily bias for a same-day scalp — on a conflict, the tape wins; the daily read just sets the lean.

**Step 3 — level map.** Call `get_quote` (prev close, day H/L, 52w), `get_timesales` (prior or current session, 15min — for intraday structure), and `get_vwap` (if open). Map and state as **price points**:
- Prior-day high / low / close (the primary pivots).
- Overnight / pre-market range; opening-range high/low (once 9:30–9:45 prints).
- Key MAs from Step 2 (SMA50, SMA20), lower/upper Bollinger band.
- Round numbers inside the range.
- VWAP + its slope (once open).
For deeper structural S/R, defer to `/ta $ARGUMENTS.symbol` rather than re-deriving — reuse, don't duplicate.

**Step 4 — fragility check.** Flag anything that weakens the bias: daily OBV divergence (from Step 2), DIX accumulation-into-weakness, price sitting on a major level (bounce/break risk). If fragile → shrink size, shorten leash. **Caveat — daily OBV is a ~20-day signal:** it speaks to the *multi-week* structure (distribution vs accumulation), NOT whether a specific session's move had buyers. To judge participation of *today's / the prior session's* move, use **session volume vs avg + volume on the breakout/close bars** (`get_quote` + `get_timesales`), not daily OBV. Never read a 20-day divergence as "today's rally was hollow" — right signal, wrong altitude.

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

A quick "where are we" relative to the prep map. **This is lagging context — the Webull chart + the four Live-layer panels are the real-time surface. Do not use this to chase.**

Call `get_quote` + `get_vwap` + `get_timesales` (last ~10 1-min bars) for `$ARGUMENTS.symbol`. Output 3 lines max:
- **Price vs VWAP** (side + slope) and distance to the nearest mapped edge.
- **Recent volume** behavior (expanding into a move = real; fading = suspect).
- **One verdict:** *"at an edge — here's the setup (level/target/stop)"* OR *"middle of range — no trade"* OR *"trigger fired: [what]."*

Never expand `check` into a trade recommendation beyond naming the setup at an edge. If price is mid-range, the only correct answer is "no trade, wait."

---

*v1. If scalping matures across sessions, extract the framework + regime playbook into `docs/scalping-playbook.md` and reference it here (the way `/ta` references its playbooks), rather than growing this file.*
