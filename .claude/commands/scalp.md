---
description: Intraday /MES index-futures scalp workflow — pre-session prep (regime + daily bias + level map + discipline checklist) and post-session review grading the trading-scalper daemon's PAPER tracker + the shadow VAP/volume-rate observer. Prep draws the level map on SPY (the tradeable S&P 500 proxy) and writes the daemon's session-plan YAML (levels + per-level direction). Paper-only — no real futures account yet, so review grades the bot, not real fills. Built to enforce discipline, not to generate more setups.
arguments:
  - name: mode
    description: Sub-mode — omit for default (pre-session prep); or `review` (post-session PAPER-tracker grading) / `check` (thin live snapshot)
    required: false
---

Intraday /MES futures scalp workflow, mode **$ARGUMENTS.mode** (default: pre-session prep). The traded instrument is **/MES** (Micro E-mini S&P 500, the paper daemon's instrument); the level map is drawn on **SPY** (the S&P 500 index /MES tracks — Tradier's MCP tools cover SPY, not futures) and **scaled ×10 to /MES prices** (SPX ≈ SPY × 10 ≈ /MES, e.g. SPY 630 → /MES 6300).

## Role and guardrails — read first

This skill supports **intraday 0–1DTE option scalping** on the index ETFs. Its purpose is to **enforce discipline**, not to manufacture setups. The lesson that created it (see memory `project-qqq-scalping`): the *reads* are usually fine — good losses come from no stops, chasing, and trading the middle. So this skill leans on the side of *fewer, cleaner trades*, and every mode ends in a discipline artifact, not a trade signal.

Four guardrails apply to every mode:

1. **Discipline over analysis.** Pre-session output ALWAYS ends with the discipline checklist. More setups ≠ better. If the day has no clean edge, the correct output is "no-trade conditions — sit out." Even paper: a sloppy level map pollutes the track record the go-live gate reads, so bias toward fewer, cleaner edges.
2. **Data limits — be honest about them.** `get_technical_indicators` is **daily-only** (no intraday bars from any tool). **Daily signals draw the map and set the lean — they never pull the trigger.** Levels (SMA20/50, Bollinger bands, prior H/L/C), the range envelope (ATR), and the day-type prior (ADX/±DI) are the *right* use; the momentum/participation oscillators (RSI, MACD, **OBV**) describe a **multi-week state** and must never be read as same-session timing or participation. The real scalper's edge — Level 2 / order flow / tape speed — is **not in this toolset**; it's on a live futures chart. This skill is **prep + paper-review + lagging context**, NOT the live execution surface.
3. **Analyze SPY, trade /MES.** The gamma map + levels come from **SPY** (the tradeable S&P 500 proxy — the equity MCP tools don't cover futures) and are **scaled ×10 to /MES prices** (SPX ≈ SPY × 10 ≈ /MES). Never try to pull /MES quotes/chains/gamma from the equity tools — they won't resolve. The daemon watches + paper-trades /MES off the scaled levels.
4. **Paper-only — no real click.** The daemon auto-executes every confirmed setup in an in-memory broker; there is **no real futures account yet**, so nothing here green-lights a real trade. Produce the map, the levels, the rules; the daemon builds the track record. Do not encourage more trading; bias toward "wait."

Parse `$ARGUMENTS.mode`: empty → `prep` (default). Valid: `prep`, `review`, `check`.

---

## Live layer — the discretionary read (reference only)

> **Post-migration note (2026-07-12):** this section describes the **equities** live-execution surface (Webull Premium, SPY/QQQ options) from before the futures migration. The **/MES paper daemon needs none of it** — it auto-executes off the level map, and there is no real futures account to trade. It's **retained as tape-reading education** for a future live-futures surface (a DOM/tape on a futures platform would replace the Nasdaq-specific NOII panel). Skip to **Mode `prep`** for the actual workflow.

`/scalp prep` draws the **map and the lean**. The **live trigger** was never in this toolset — it's on your screen, across four panels. Read all four **only when price is at a pre-mapped edge** (Step 3); mid-range they're noise.

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

Run this before the open (or early in the session). One command that produces the day's map + the rules, and writes the `trading-scalper` daemon's session-plan file so the daemon watches (and paper-trades) the same edges.

**Step 0 — clock + macro-event gate.** Call `get_market_clock`. If pre-market, VWAP/timesales have no current-session data → build levels from the **prior** session (note it). If open, use live data.

Then call **`get_upcoming_economic_releases(days_ahead=1)`** and check for a release dated *today*. The gamma map (Step 1) is built off OCC-settled OI that is **one session stale and cannot be refreshed intraday** — so an event that breaks the map mid-session voids the whole plan, and a daemon left on a stale `mode` will fade a level that's actually breaking (the 2026-06-17 FOMC lesson: an all-day fade map was blessed across a 2:00 PM statement; the pin broke down post-presser and the morning map was void by 3:00). But **not every macro event matters to an intraday scalp** — gate on *when* it lands and *whether it can flip the regime*, not on mere presence. The tool returns Date + Category only (no time), so map each release to its **conventional ET release time** (fixed by the issuing agency) and classify:

| Class | Releases (conventional ET time) | Treatment |
|---|---|---|
| **1 — Pre-market (8:30)** | CPI, NFP, PCE/Personal Income & Outlays, GDP, PPI, Retail Sales, Durable Goods, Housing Starts/Permits, Jobless Claims, Trade | Already in price by 9:30 — sets the day's *tone*, doesn't whipsaw mid-session. **Not** a no-trade window. Run prep *after* the 8:30 print so the map reflects it; note elevated open IV + that the opening range *is* the reaction. |
| **2 — RTH morning (10:00)** | ISM Mfg/Services, JOLTS, New/Existing Home Sales, Consumer Confidence, Michigan sentiment | Lands inside the 9:30–10:30 window; tier-2, rarely flips a gamma regime. Soft caution only: let the first 30–45 min set the opening range before fading. No blank. |
| **3 — RTH regime event (2:00)** | **FOMC decision, FOMC minutes, Fed Chair presser** | Breaks the map mid-session *and* can flip the GEX regime sign. **Cap the plan to the pre-2:00 morning window**, pre-write `lean: no-trade` from ~1:45 ET through the close, and re-map next session after OI re-settles. This is the only class that gets the stand-down blank. |

Only a **Class-3** event present today forces the `lean: no-trade` cap (note it loudly in the plan + the Step 7 checklist). A **Class-1** event is a *sequencing* instruction (don't prep before 8:30; the map is unreliable until the print lands). A **Class-2** event is a one-line caution on the opening range. If today's releases are all low-tier pre-market (e.g. a lone Initial Jobless Claims), it's a **normal scalp day** — don't over-fire the gate. If a Class-3 event has *already* released earlier today (mid-session re-run), treat the existing map as stale and default the plan to `lean: no-trade` until the next session's prep.

**Step 1 — regime + the gamma map (the day-type filter).** Call **`get_gamma_profile SPY`** (default aggregate mode) — the S&P 500 GEX read (SPY is the tradeable proxy; **its walls come back at SPY prices ~630 — scale ×10 to /MES ~6300 when you write the Step 6 plan**). One call now divides the sources correctly: the **regime sign + zero-gamma flip come from the front (0-1DTE) expiration** (the intraday-honest read), while the **call wall / put wall come from the ≤7-DTE aggregate**. Take the **`Regime` row as the day-type label** (it's the front-exp sign — *don't* re-derive a regime from anything else) and the **walls as your edges:** across the next few expirations the persistent high-OI round strikes surface the *structural* magnets — stable through the session and far enough from spot to be fadeable — whereas on the 0DTE expiration gamma collapses onto ATM, so its "walls" sit on spot, migrate all session, and can't be pre-mapped. **If a `⚠ Regime Conflict` row appears** (the ≤7-DTE aggregate sign disagrees with the front-exp sign — the 6/16 mislabel that blessed an all-day fade map the bot bled on), trust the front-exp label and treat the day as conflicted: lean toward a `fragile-pin`/`breakout-trend` posture and the verdict modes, or stand down. The `Zero-Gamma Flip` row is the front-exp flip — carry it straight into Step 6's tripwire (no second call needed). Then call `get_dix_gex` as the **SPX-wide sanity prior** (EOD, one day stale): GEX sign + **1-month percentile** for the fragility read, plus DIX accumulation/distribution as background. Translate to a scalp playbook:
- **Positive GEX** → dealers suppress vol. Range/mean-revert day: **fade the walls** back toward the flip/VWAP (`regime: pin`). Call wall caps, put wall supports. (Step 6 sets the per-wall resolution.)
- **Positive GEX but low SqueezeMetrics percentile (≤~10) / small total GEX** → suppression is *thinning*. Still a pin, but **fragile** — a volume break can round-trip the fade. Flag it (`regime: fragile-pin`); it's the trap, and the **conflicted wall the verdict modes (`reversal`/`retest`) are built for** (Step 6).
- **Negative GEX** → dealers amplify. Trend/momentum day: **trade the wall break** (`regime: breakout-trend`), never fade — via `break` for a clean runaway or `reversal`/`retest` for a false-break-prone wall (Step 6). The zero-gamma flip is the line that, once crossed, confirms the trending regime.
- DIX divergence is background, not a same-day trigger.

**Step 2 — daily bias (a weak prior, not a verdict).** Call `get_technical_indicators` (daily). Use it for **levels + day-type only**: **ADX** (>25 = real trend, <20 = chop/no-trend) and **+DI/-DI** set whether it's even a trend day and which way; price vs **SMA20/SMA50** + Bollinger bands are *levels* feeding Step 3; **ATR** is the range envelope for Step 5. **RSI / MACD / OBV here are multi-week state — they color the lean and the fragility check, never an intraday entry.** Output one line: "which direction am I *allowed* to scalp, and is it even a trend day." **State the override rule:** the intraday tape (VWAP + structure) overrules this daily bias for a same-day scalp — on a conflict, the tape wins; the daily read just sets the lean.

**Step 3 — level map.** Call `get_quote` (prev close, day H/L, 52w), `get_timesales` (prior or current session, 15min — for intraday structure), and `get_vwap` (if open). Map and state as **price points**:
- Prior-day high / low / close (the primary pivots).
- Overnight / pre-market range; opening-range high/low (once 9:30–9:45 prints).
- Key MAs from Step 2 (SMA50, SMA20), lower/upper Bollinger band.
- Round numbers inside the range.
- VWAP + its slope (once open).
For deeper structural S/R, defer to `/ta SPY` rather than re-deriving — reuse, don't duplicate.

**Step 4 — fragility check.** Flag anything that weakens the bias: daily OBV divergence (from Step 2), DIX accumulation-into-weakness, price sitting on a major level (bounce/break risk). If fragile → shrink size, shorten leash. **Caveat — daily OBV is a ~20-day signal:** it speaks to the *multi-week* structure (distribution vs accumulation), NOT whether a specific session's move had buyers. To judge participation of *today's / the prior session's* move, use **session volume vs avg + volume on the breakout/close bars** (`get_quote` + `get_timesales`), not daily OBV. Never read a 20-day divergence as "today's rally was hollow" — right signal, wrong altitude.

**Step 5 — the plan.** Output the day's structure tightly:
- **The edges:** support edge ↔ resistance edge (the range you fade inside, or the breakout level you go with).
- **Rank edges by confluence:** a Step-1 gamma wall (outer, structural) sitting on a Step-3 technical (prior-day H/L, VWAP, round number) is the highest-confidence edge — trade those first. A wall with no technical nearby is softer (OI-staleness-sensitive); a technical with no gamma behind it can slice through. Gamma supplies the *outer* edges; technicals supply the *inner* levels.
- **Regime playbook:** pin = fade edges to VWAP; breakout = go-with on the pullback-hold, or stand aside (never fade a volume breakout).
- **Invalidation:** the price that flips the regime (range edge breaking on volume = pin over).
- **Expected range / sizing input:** ATR(14) from Step 2 as % of price → the realistic intraday range; size targets/stops as fractions of it.

**Step 6 — write the daemon's session plan (`~/.trading/scalp/{date}-{key}.yaml`).**

The `trading-scalper` paper daemon (see `docs/scalper-automation.md`) watches these same edges off the live **/MES** tape and **paper-trades** them — auto-placing a direction-aware bracket in an in-memory broker so the detector builds a reviewable track record. The plan file **is** the handoff: prep draws the map (SPY walls, scaled ×10), the daemon watches /MES. Emit it now.

1. **Pick the resolution(s) per wall, then assign a direction to each.** The walls from Step 1 are the edges; *which resolution(s) you trade* at each edge is decided here — by the regime sign **and the wall's character**. A wall has three physical resolutions (touch-and-reject, cross-and-fail, cross-and-hold); the four modes express them. **The daemon never picks a mode — it executes whatever you write here, and can't recompute GEX intraday — so this is the only place the verdict modes get deployed. Don't default trend days to bare `break`; route to the tree:**

   | Regime (Step 1) | Wall character | Emit at the wall |
   |---|---|---|
   | **+GEX pin** (healthy GEX) | clean magnet | **`fade`** only (mean-revert to the flip/VWAP). |
   | **+GEX fragile-pin** (thin GEX / low percentile) | may round-trip the fade | **`fade`** + **`reversal`** + **`retest`** — *the* conflicted wall: fades if it holds, snaps back if it pokes-and-fails, goes with it if it breaks-and-holds. |
   | **−GEX trend** | clean accelerant, price approaching with momentum from afar | **`break`** (catch the runaway) — or **`retest`** to enter patient and skip false breaks (accepts missing a runaway that never pulls back). |
   | **−GEX trend** | conflicted: price wedged near / oscillating around the wall (the 6/22 type) | **`reversal`** + **`retest`**, drop `break` (a bare break round-trips here). |

   **Mode → trade direction** (the detector reads `direction` straight from the level — no contract):
   - **`fade`** (mean-revert at the wall): put wall (support) → **long**, call wall (resistance) → **short**.
   - **`break`** (fire on the cross, *with* it): resistance → **long** (up-break), support → **short** (down-break).
   - **`retest`** (confirmed break, pull-back-and-resume — patient continuation): **same as `break`** — resistance → long, support → short.
   - **`reversal`** (failed break, snap-back — *opposite* the attempt): **same as `fade`** — resistance → short (failed up-break, back down), support → long (failed down-break, back up).

   **`side` = the break direction** (consistent across `break`/`reversal`/`retest`): `resistance` = an up-break, arm from below; `support` = a down-break, arm from above — so a downside breakdown of an *upper* wall is written `side: support`. For a `fade`, `side` is just the wall type. **Express a verdict wall as up to two rows at one price+side** — a `reversal` row + a `retest` row, each naming its own `direction`; one state machine per wall drives both and fires whichever resolves (use either alone or both).

   **Fire geometry + gating:** `fade` fires on a touch-and-reject within the band; `break` on a cross + follow-through; `reversal`/`retest` on the state machine's verdict (confirmation, not the bare cross). **`fade`/`break` also require tape confirmation** (a long wants buyers lifting offers, a short sellers hitting bids); **`reversal`/`retest` are geometry + lean only — NOT tape-gated** (the snap-back *timing* is the signal). `lean` gates trade *direction*: `long-only` permits any long (including a breakout long at a resistance wall), `short-only` any short, `both` either, `no-trade` none. Attach a `direction` **only** to the walls/resolutions the lean permits; leave the rest alert-only.

   **No contract to pick — the future *is* the instrument.** Scale each SPY gamma wall ×10 to its /MES price (SPY 630 → /MES 6300) and set the level `price` to the /MES value. There is no expiry / strike / OCC step — that whole options layer is gone. Optionally set explicit `stop`/`target` /MES prices per level; otherwise the plan's `default_stop_points` / `default_target_points` derive them from the level.

2. **Write the file** (Write tool) to `~/.trading/scalp/{date}-{key}.yaml` — `{date}` = the session date `YYYY-MM-DD`, `{key}` = the plan `symbol` without the leading `/` and the `:XCME` suffix (e.g. `/MESU26:XCME` → `MESU26`; the daemon derives the same key from `--symbols`). Shape:

```yaml
date: 2026-07-12               # session date — MUST match the daemon's run date or it won't load
symbol: /MESU26:XCME           # the current /MES front-month dxFeed streamer symbol (what dxFeed echoes as eventSymbol)
regime: pin                    # pin | fragile-pin | breakout-trend  (from Step 1 GEX sign)
lean: both                     # long-only | short-only | both | no-trade  (Step 1 + Step 2)
contracts: 1                   # qty per setup
default_stop_points: 6         # child stop = level ∓ pts (below a long / above a short); each pt = $5
default_target_points: 8       # child take-profit = level ± pts
zero_gamma: 6300.0             # the gamma flip (SPY flip ×10) — bidirectional tripwire; alerts on a cross, no trade
levels:                        # the gamma walls (SPY ×10); each names the trade DIRECTION if it tags
  # POSITIVE GEX → fade: put wall (support) → long, call wall (resistance) → short
  - {price: 6280.0, side: support,    mode: fade, direction: long,  stop: 6275.0, target: 6292.0}
  - {price: 6320.0, side: resistance, mode: fade, direction: short, stop: 6325.0, target: 6308.0}
session_caps:                  # recorded for your discipline (see caveat) — not daemon-enforced
  max_trades: 3
  daily_stop_usd: 150
notes: "Clean +GEX pin (SPY levels ×10). Fade the walls back to the 6300 zero-gamma flip; a break of 6300 on volume = regime flipped to trend — the tripwire pings, re-run /scalp prep (a fragile-pin or trend wall would instead carry reversal/retest rows, see below)."
```

**Verdict-wall shape** — a fragile-pin or −GEX conflicted wall, expressed as the two resolution rows at one price (the snap-back + the continuation). This example is an up-break of a resistance wall; for the 6/22-style *downside* breakdown, write `side: support` and flip the directions (reversal → long, retest → short):
```yaml
  - {price: 6250.0, side: resistance, mode: reversal, direction: short, stop: 6255.0}
  - {price: 6250.0, side: resistance, mode: retest,   direction: long,  stop: 6244.0}
```

**Verdict-mode calibration + caveats** (full log: memory `project-scalper-verdict-calibration`): timers/margins were **calibrated 2026-06-23** off the 6/18 (chop) + 6/22 (740 breakdown) tape. The 6/22 win replayed as a **`retest` GO_WITH** (confirmed breakdown → retest-fail → resume down), so the GO_WITH path is well-fit; the **`reversal` path is still lightly evidenced** (no clean fast-false-break in-window) — treat reversal fires especially as a *prompt to look*, not an auto-blessed bracket (the paper book records either way). **Don't arm verdict rows on a clean +GEX pin** — they belong on fragile-pin / trend / conflicted walls per the tree above; a clean pin is a `fade`/stand-aside day.

**Always set `zero_gamma`** — a dedicated **bidirectional tripwire**, not a tradeable level: the daemon fires a *non-trading* "regime may be inverting — re-run `/scalp prep`" alert when the underlying crosses it either way. It's the cheap guard against the worst loss mode — a stale regime label feeding each level's `mode`, so the bot fades a level that's actually breaking. The daemon **never recomputes GEX** (the stream has no OI/greeks), so the flip stays this static number; on a cross, *you* re-pull the map. **Use the `Zero-Gamma Flip` from Step 1's output** — `get_gamma_profile`'s aggregate mode already sources the flip from the front (0-1DTE) expiration (the ≤7-DTE aggregate smears it — on real QQQ the aggregate flip came back degenerate above spot while the front expiration gave the clean near-spot pin ~720), so no second call is needed. The sources divide cleanly inside the one call: **front-exp → regime + flip; aggregate → walls** (and a `⚠ Regime Conflict` row when the two signs disagree).

3. **State these caveats after writing — they are easy to get wrong:**
   - **The bracket is in absolute /MES points/prices, not a premium %.** `default_stop_points` / `default_target_points` default to **6 pt / 8 pt** offsets from the level (stop below a long / above a short; target the mirror); an explicit `stop`/`target` price on a level wins. On /MES **each point = $5** (a 6-pt stop risks $30/contract), and the daemon rounds every child to the 0.25 tick. `level.stop` is now **load-bearing** — the real paper stop, not alert-text.
   - **Scale SPY → /MES ×10.** Every level `price`, `stop`, `target`, and `zero_gamma` is a /MES price (~6300), i.e. the SPY gamma wall × 10. A wall left at SPY scale (~630) will never tag — the tape prints ~6300.
   - **`mode` + tape gate the fire** (`fade`/`break` only). `fade` fires on a touch-and-reject within the band; `break` fires only after price crosses the wall with follow-through. Both also need the **tape to confirm** (a long needs buyers lifting offers; a short needs sellers hitting bids). **`reversal`/`retest` are the exception — geometry + lean only, NOT tape-gated.** A confirmed setup on a crossed/locked book skips the paper fill (alerts only). There is **no bare-touch heads-up**: an unconfirmed tag stays silent.
   - **`session_caps` are recorded, not enforced.** The paper daemon has no discipline engine; max-trades / daily-stop live in the file for *your* record (and the Step 7 checklist) — honor them yourself.
   - **The subscribe symbol is fixed at launch.** The daemon subscribes to `symbol` at startup; a new front-month contract (or a symbol change) mid-session needs a restart (levels/lean/direction still hot-reload for alerting).
   - **Graceful degrade:** a level with no `direction` is alert-only; no file at all = the daemon stays silent.
   - **Run it:** `uv run --package trading-scalper trading-scalper --symbols /MESU26:XCME` (the plan's `symbol`). Needs `[tastytrade]` in `~/.tradingrc` (DXLink feed) + a funded customer account for CME data. The daemon also writes shadow volume telemetry (`{date}-tape.jsonl` raw /MES tape + `{date}-shadow.jsonl` POC/value-area + volume-rate snapshots) — recorded, gating nothing. After the close, `/scalp review` grades the daemon's paper record (`{date}.jsonl` + `{date}-signals.jsonl` + `{date}-summary.json`) and the shadow observer.

**No-trade day:** still write the file with `lean: no-trade` and your reference levels but **no `direction` fields** — the daemon prints the banner and stays silent (never prompts, never paper-trades).

**Step 7 — the discipline checklist (ALWAYS print this last, verbatim-style):**

> **Before blessing every level in the plan:**
> - [ ] Name the **level + target + stop** (all /MES prices). Can't name all three → it's not a level, leave it alert-only.
> - [ ] **Hard stop is real** (points × $5 = the risk; e.g. 6 pt = −$30/contract). No negotiation, no "it'll come back."
> - [ ] The edge is a **named confluence** (gamma wall on a technical), not the middle of the range.
> - [ ] The mode is **not a chase** — `retest`/`reversal` over bare `break` where the wall is conflicted.
> - [ ] `contracts` is **A+-only size**; a marginal edge is 1 lot or alert-only.
> - [ ] The regime is one the day actually supports (don't arm verdict rows on a clean pin).
>
> **Session caps:** max __ trades, daily stop −$__ (ask the user to set both if not already fixed). These are the `session_caps` values in the Step 6 daemon plan — the daemon records them, but they're your discipline reference (it doesn't enforce them, and paper P&L isn't real money — the point is the *habit*).

---

## Mode `review` — post-session trade grading

The feedback loop on the **paper detector** — the bot's own track record. There's no real futures account yet, so review grades the daemon, not your fills (when you open one, add a real-fills grade back here). Run after the close (or when the user says "done").

**Step 1 — grade the paper detector (the tracker).** The daemon keeps its track record under `~/.trading/scalp/paper/` — it paper-trades every confirmed fire. Grade it; this is what builds the verdict-mode calibration evidence (`project-scalper-verdict-calibration`) and the go-live gate sample.
- Read the three joinable artifacts: `{date}-summary.json` (realized P&L + `n_fills`, recomputed restart-safe from the log), `{date}-signals.jsonl` (one row per **fire** — `mode` / `side` / `level` / `confirming` / `bracket_id` + the recorded B4 telemetry), and `{date}.jsonl` (one row per **fill** — each carries `bracket_id` + `realized_delta`, the win/loss label on the close).
- **Join fires → outcomes on `bracket_id`** (a fire's `bracket_id` = the entry-order id shared by its bracket's fills; `null` = an alert-only / spread-suppressed fire that placed no paper trade). The key is recorded — no fragile symbol+timestamp reconstruction.
- **Grade by mode.** Tally fade / break / reversal / retest fires and their paper win/loss + per-contract magnitude (each /MES point = $5). The verdict modes are what to watch: GO_WITH/`retest` is well-fit, **`reversal` is still thin** — note *every* new reversal/retest sample and append it to `project-scalper-verdict-calibration` (the calibration log needs in-window failed-break samples). **The 0.4 (futures) cohort starts fresh** — the QQQ-era counts don't carry into it.
- **Machine-gun check.** Fires-per-level — the per-level cooldown should keep this low. A level with many fires = the cooldown isn't biting, or the regime gate should have sat the day out; flag it. (Geometry constants are rescaled ×10 for /MES and recalibrating — also watch for a band that's now mis-scaled.)
- **Cross-session cohort status — run the scorecard, don't hand-tally.** The by-mode counts above are the *single-session* read (what fired today, cooldown check, new verdict sample). For where the *accumulated* record stands against the go-live gate, run `uv run --package trading-scalper trading-scalper-scorecard` — the authoritative per-(version cohort × mode) tally (n / win rate / expectancy + 95% LB / profit factor / max DD / session concentration) plus the current-cohort gate verdict (`project-scalper-golive-gate`). Prefer it over recomputing from the JSONLs. **Cadence — don't reprint the full table every session:** the gate needs n≥50 per cohort, so one session barely moves it. Surface just the **one-line current-cohort gate status** each review (keeps the finish line visible); pull the full table + `--chart` deliberately — right after a version bump (confirm the cohort reset) or as a mode climbs toward n=50. Going live is a periodic decision — pull the full read at a deliberate checkpoint, not every session.

**Step 2 — grade the shadow observer (VAP + volume-rate) — SHADOW, evidence-only.** The shadow recorder (`feedback_shadow_then_live`) writes `{date}-tape.jsonl` (raw /MES tape) + `{date}-shadow.jsonl` (POC / value-area + volume-rate snapshots). It **gates nothing** — this step only accumulates the evidence to settle whether the break-side VAP read predicts a runner (`project-scalper-improvements` open #1). It must NOT change how the trades above were graded.
- **The decision artifact is a contingency table.** For each wall cross this session: was the break side a **void** or an **HVN** (`VolumeProfile.break_side_read`, or rebuilt from `{date}-tape.jsonl`), and did price then **run** or **oscillate**? Reconstruct from the plan's walls (`{date}-{key}.yaml`) + the raw tape — find each cross, classify the break side, label ran-vs-oscillated from the subsequent path. Add this session's row(s) to the void→ran / hvn→oscillated table in `project-scalper-improvements` open #1.
- **Volume-rate (lower priority).** At each cross/fire, was the move on expanding or contracting volume (`ratio` >1 / <1)? Note whether expansion lined up with the paper winners — but this is the **confidence/size modulator** idea, **never a fire gate** (B4 died gating on tape; 6/29's retest won against an 8:1 sell tape).
- **Stay shadow until it separates.** n is tiny — one session is one or two rows; don't over-conclude from a single day, and do not wire the read into the plan or the daemon. The promotion bar is the table separating across multiple conflicted-box sessions (`feedback_shadow_then_live`).

---

## Mode `check` — thin live snapshot (use sparingly)

A quick "where are we" relative to the prep map. **This is lagging context — the live chart + the daemon's own prompts are the real-time surface. Do not use this to chase.**

Read SPY (the tradeable S&P 500 proxy — the MCP quote/vwap tools don't cover the /MES contract; ×10 the SPY price to compare against the /MES level map). Call `get_quote` + `get_vwap` + `get_timesales` (last ~10 1-min bars) for **SPY**. Output 3 lines max:
- **Price vs VWAP** (side + slope) and distance to the nearest mapped edge.
- **Recent volume** behavior (expanding into a move = real; fading = suspect).
- **One verdict:** *"at an edge — here's the setup (level/target/stop)"* OR *"middle of range — no trade"* OR *"trigger fired: [what]."*

Never expand `check` into a trade recommendation beyond naming the setup at an edge. If price is mid-range, the only correct answer is "no trade, wait."

---

*v1. If scalping matures across sessions, extract the framework + regime playbook into `docs/scalping-playbook.md` and reference it here (the way `/ta` references its playbooks), rather than growing this file.*
