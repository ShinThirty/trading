---
description: Intraday index-futures scalp workflow (/MES default). Prep — regime + daily bias + level map + discipline checklist; writes the trading-scalper daemon's session-plan YAML (gamma walls from the traded future's cash index, SPX for /MES / NDX for /MNQ, shifted to the future by the live carry basis; per-level direction). Review — grade the daemon's PAPER tracker + shadow observers. Check — thin live snapshot. Paper-only.
arguments:
  - name: mode
    description: Sub-mode — omit for default (pre-session prep); or `review` (post-session PAPER-tracker grading) / `check` (thin live snapshot)
    required: false
---

Intraday index-futures scalp workflow, mode **$ARGUMENTS.mode** (default: pre-session prep). Traded instrument defaults to **/MES**.

Parse `$ARGUMENTS.mode`: empty → `prep` (default). Valid: `prep`, `review`, `check`.

## Rules (every mode)

- **Reference cash index** = SPX for /MES, /ES; NDX for /MNQ, /NQ. Auto-resolved from `--symbols` (`Instrument.reference`); don't hardcode. Examples below use SPX/`/MES`; swap NDX + Nasdaq-scale prices for /MNQ.
- **Gamma walls come from the cash index** (`get_gamma_profile <reference>`), in index points → shift to futures price by the **live carry basis** (`future − index`, ≈ +50 RTH for /MES) from `trading-scalper --basis`. Never pull futures quotes/chains/gamma from equity tools.
- **Daily tools only** — no intraday bars from any MCP tool. Daily signals draw the map + set the lean; they never trigger. Intraday tape (VWAP + structure) lives on the live chart / daemon.
- **Paper-only** — daemon auto-executes into an in-memory broker; no real futures account. Nothing here green-lights a live trade.
- **Prep always ends with the discipline checklist.** No clean edge → output "no-trade, sit out." Bias toward fewer, cleaner edges.

---

## Mode `prep` — pre-session setup

Run before the open (or early in session). Produces the day's map + rules and writes the daemon's session-plan YAML.

**Step 0 — clock + macro-event gate.** Call `get_market_clock`. Pre-market → build levels from the prior session (note it). Open → live data.

Call `get_upcoming_economic_releases(days_ahead=1)`; find releases dated *today*. The gamma map is one session stale and can't refresh intraday. Map each release to its conventional ET release time and classify:

| Class | Releases (conventional ET time) | Treatment |
|---|---|---|
| **1 — Pre-market (8:30)** | CPI, NFP, PCE/Personal Income & Outlays, GDP, PPI, Retail Sales, Durable Goods, Housing Starts/Permits, Jobless Claims, Trade | In price by 9:30. Run prep *after* the 8:30 print. Not a no-trade window; note elevated open IV, opening range = the reaction. |
| **2 — RTH morning (10:00)** | ISM Mfg/Services, JOLTS, New/Existing Home Sales, Consumer Confidence, Michigan sentiment | Lands in the 9:30–10:30 window; rarely flips a regime. Let the first 30–45 min set the opening range before fading. |
| **3 — RTH regime event (2:00)** | FOMC decision, FOMC minutes, Fed Chair presser | Breaks the map mid-session, can flip the GEX sign. Cap the plan to the pre-2:00 morning window, pre-write `lean: no-trade` from ~1:45 ET to close, re-map next session. |

- Class-3 today → force `lean: no-trade` cap (note in plan + Step 7 checklist).
- Class-1 → sequencing only (don't prep before 8:30).
- Class-2 → one-line caution on the opening range.
- All low-tier pre-market (e.g. lone Jobless Claims) → normal scalp day.
- Class-3 already released earlier today (mid-session re-run) → treat the map as stale, default `lean: no-trade` until next prep.

**Step 1 — regime + gamma map.** Call `get_gamma_profile <reference>` (aggregate mode; SPX for /MES, NDX for /MNQ). Sources divide inside the one call:
- **Regime sign + `Zero-Gamma Flip`** ← front (0-1DTE) expiration. Take the `Regime` row as the day-type label; carry `Zero-Gamma Flip` to Step 6.
- **Call wall / put wall** ← ≤7-DTE aggregate.
- **`⚠ Regime Conflict` row present** (aggregate sign ≠ front-exp sign) → trust front-exp, treat the day as conflicted (fragile-pin / breakout posture + verdict modes, or stand down).

Then (S&P complex only) call `get_dix_gex`: GEX sign + 1-month percentile (fragility), DIX accumulation/distribution as background. Skip for /MNQ.

Playbook:
- **Positive GEX** → `regime: pin`. Fade walls back to flip/VWAP. Call wall caps, put wall supports.
- **Positive GEX + low percentile (≤~10) / small total GEX** → `regime: fragile-pin`. Fade can round-trip; the wall for the verdict modes (`reversal`/`retest`).
- **Negative GEX** → `regime: breakout-trend`. Trade the break, never fade. Zero-gamma flip = the trend-confirm line.

**Step 2 — daily bias.** Call `get_technical_indicators` (daily). Use: ADX (>25 trend, <20 chop) + ±DI (trend-day + direction); SMA20/SMA50 + Bollinger bands = levels for Step 3; ATR = range envelope for Step 5. RSI / MACD / OBV = multi-week color only, never intraday timing. Output one line: allowed scalp direction + is it a trend day. Tape overrules this daily bias on a conflict.

**Step 3 — level map.** Call `get_quote <reference>` (prev close, day H/L) + `get_timesales <reference>` (prior/current session, 15min). Express in cash-index points, then basis-shift to the future. Map as prices:
- Prior-day high / low / close.
- Round numbers inside the range (same on both scales — SPX 7600 = /MES 7600 in points; still add basis to the *wall* prices from Step 1).
- Key MAs (SMA50, SMA20), lower/upper Bollinger band.
- Overnight/pre-market range, opening-range H/L, VWAP — /MES-native (daemon computes off its own tape; read off the live chart, not scaled from SPX).

For deeper S/R defer to `/ta <reference>` (`/ta SPX` for /MES).

**Step 4 — fragility check.** Flag: daily OBV divergence (Step 2), DIX accumulation-into-weakness, price sitting on a major level. Fragile → shrink size, shorten leash. Daily OBV is a ~20-day signal — for *today's* participation use session volume vs avg + breakout/close-bar volume (`get_quote` + `get_timesales`), not OBV.

**Step 5 — the plan.** Output tightly:
- **Edges:** support edge ↔ resistance edge.
- **Rank by confluence:** gamma wall (outer, structural) on a technical (prior-day H/L, VWAP, round number) = highest confidence, trade first. Wall with no technical = softer; technical with no gamma = can slice through.
- **Regime playbook:** pin = fade edges to VWAP; breakout = go-with on the pullback-hold or stand aside (never fade a volume breakout).
- **Invalidation:** the price that flips the regime.
- **Expected range:** ATR(14) as % of price; size targets/stops as fractions of it.

**Step 6 — write the daemon's session plan** (`~/.trading/scalp/{date}-{key}.yaml`).

1. **Pick resolution(s) per wall, then a direction for each** — by regime sign + wall character:

   | Regime (Step 1) | Wall character | Emit at the wall |
   |---|---|---|
   | **+GEX pin** (healthy GEX) | clean magnet | **`fade`** only (mean-revert to flip/VWAP). |
   | **+GEX fragile-pin** (thin GEX / low percentile) | may round-trip the fade | **`fade`** + **`reversal`** + **`retest`**. |
   | **−GEX trend** | clean accelerant, momentum from afar | **`break`** — or **`retest`** to enter patient and skip false breaks. |
   | **−GEX trend** | conflicted: price wedged near / oscillating the wall | **`reversal`** + **`retest`**, drop `break`. |

   **Mode → trade direction** (detector reads `direction` straight from the level):
   - **`fade`** (mean-revert): put wall (support) → **long**, call wall (resistance) → **short**.
   - **`break`** (fire on the cross, with it): resistance → **long** (up-break), support → **short** (down-break).
   - **`retest`** (confirmed break, pull-back-and-resume): same as `break` — resistance → long, support → short.
   - **`reversal`** (failed break, snap-back, opposite the attempt): same as `fade` — resistance → short, support → long.

   **`side` = the break direction** (across `break`/`reversal`/`retest`): `resistance` = up-break, arm from below; `support` = down-break, arm from above — a downside breakdown of an upper wall is written `side: support`. For `fade`, `side` = the wall type. Express a verdict wall as up to two rows at one price+side (a `reversal` row + a `retest` row, each with its own `direction`); one state machine per wall drives both.

   **Fire geometry + gating:** `fade` = touch-and-reject in the band; `break` = cross + follow-through; `reversal`/`retest` = the state machine's verdict. `fade`/`break` also require **tape confirmation** (long wants buyers lifting offers, short wants sellers hitting bids). `reversal`/`retest` are **geometry + lean only, NOT tape-gated**. `lean` gates trade direction: `long-only` permits any long, `short-only` any short, `both` either, `no-trade` none. Attach `direction` only to walls the lean permits; leave the rest alert-only.

   **Basis-shift each wall:** futures price = cash-index wall + live basis (SPX 7600 + basis 50 → /MES 7650); fetch with `trading-scalper --basis` (RTH only). Set level `price` to the futures value. Optionally set explicit `stop`/`target` futures prices; else `default_stop_points` / `default_target_points` derive them.

2. **Write the file** (Write tool) to `~/.trading/scalp/{date}-{key}.yaml` — `{date}` = session date `YYYY-MM-DD`, `{key}` = plan `symbol` without the leading `/` and the `:XCME` suffix (`/MESU26:XCME` → `MESU26`). Shape:

```yaml
date: 2026-07-12               # session date — MUST match the daemon's run date or it won't load
symbol: /MESU26:XCME           # /MES front-month dxFeed streamer symbol
regime: pin                    # pin | fragile-pin | breakout-trend  (Step 1 GEX sign)
lean: both                     # long-only | short-only | both | no-trade  (Step 1 + Step 2)
contracts: 1                   # qty per setup
default_stop_points: 6         # child stop = level ∓ pts (below a long / above a short); each pt = $5
default_target_points: 8       # child take-profit = level ± pts
zero_gamma: 7625.0             # gamma flip (SPX flip 7575 + basis 50) — bidirectional tripwire; alerts on a cross, no trade
levels:                        # gamma walls (SPX wall + basis); each names the trade DIRECTION if it tags
  - {price: 7600.0, side: support,    mode: fade, direction: long,  stop: 7595.0, target: 7612.0}
  - {price: 7675.0, side: resistance, mode: fade, direction: short, stop: 7680.0, target: 7663.0}
session_caps:                  # recorded for discipline — not daemon-enforced
  max_trades: 3
  daily_stop_usd: 150
notes: "Clean +GEX pin. Fade the walls to the 7625 zero-gamma flip; a break of 7625 on volume = regime flipped — tripwire pings, re-run /scalp prep."
```

**Verdict-wall shape** — fragile-pin or −GEX conflicted wall, two resolution rows at one price. Up-break of a resistance wall shown; for a downside breakdown write `side: support` and flip directions (reversal → long, retest → short):
```yaml
  - {price: 7650.0, side: resistance, mode: reversal, direction: short, stop: 7655.0}
  - {price: 7650.0, side: resistance, mode: retest,   direction: long,  stop: 7644.0}
```

3. **Caveats to state after writing:**
   - **Bracket is absolute /MES points, not a premium %.** `default_stop_points`/`default_target_points` default 6 pt / 8 pt (stop below a long / above a short); explicit level `stop`/`target` wins. Each point = $5; daemon rounds children to the 0.25 tick. `level.stop` is load-bearing.
   - **Cash-index wall + carry basis → the future.** Every `price`, `stop`, `target`, `zero_gamma` is a futures price. A wall left at cash-index scale tags ~50 pts early. Re-check the basis each session.
   - **`mode` + tape gate the fire** (`fade`/`break`); `reversal`/`retest` are geometry + lean only. A confirmed setup on a crossed/locked book skips the paper fill (alerts only). No bare-touch heads-up.
   - **`session_caps` recorded, not enforced** — honor them yourself.
   - **Subscribe symbol fixed at launch** — a new front-month / symbol change mid-session needs a restart (levels/lean/direction hot-reload).
   - **Graceful degrade:** a level with no `direction` is alert-only; no file = daemon silent.
   - **`zero_gamma` always set** — use the `Zero-Gamma Flip` from Step 1. Bidirectional tripwire; on a cross the daemon alerts "re-run /scalp prep" (it never recomputes GEX).
   - **Run it:** `uv run --package trading-scalper trading-scalper --symbols /MESU26:XCME`. Needs `[tastytrade]` in `~/.tradingrc` + a funded customer account for CME data. Streams the cash-index reference (auto-resolved; override `--reference`, disable `--reference ''`) and records the live carry basis (`{date}-basis.jsonl`, RTH only) + shadow volume telemetry (`{date}-tape.jsonl`, `{date}-shadow.jsonl`).

**No-trade day:** still write the file with `lean: no-trade` + reference levels but **no `direction` fields** — daemon prints the banner and stays silent.

**Step 7 — discipline checklist (ALWAYS print last):**

> **Before blessing every level in the plan:**
> - [ ] Name the **level + target + stop** (all /MES prices). Can't name all three → alert-only.
> - [ ] **Hard stop is real** (points × $5 = risk; 6 pt = −$30/contract). No negotiation.
> - [ ] The edge is a **named confluence** (gamma wall on a technical), not the middle.
> - [ ] The mode is **not a chase** — `retest`/`reversal` over bare `break` on a conflicted wall.
> - [ ] `contracts` is **A+-only size**; a marginal edge is 1 lot or alert-only.
> - [ ] The regime supports it (no verdict rows on a clean pin).
>
> **Session caps:** max __ trades, daily stop −$__ (ask the user to set both if unset). These are `session_caps` — recorded, not enforced; the point is the habit.

---

## Mode `review` — post-session grading

Grades the paper detector (no real account yet). Run after the close.

**Step 1 — grade the paper detector.** Read three joinable artifacts under `~/.trading/scalp/paper/`: `{date}-summary.json` (realized P&L + `n_fills`), `{date}-signals.jsonl` (one row per **fire** — `mode`/`side`/`level`/`confirming`/`bracket_id` + B4 telemetry), `{date}.jsonl` (one row per **fill** — `bracket_id` + `realized_delta`).
- **Join fires → outcomes on `bracket_id`** (`null` = alert-only / spread-suppressed fire).
- **Grade by mode.** Tally fade/break/reversal/retest fires + paper win/loss + per-contract magnitude ($5/pt). Append every new `reversal`/`retest` sample to `project-scalper-verdict-calibration`. The 0.4 (futures) cohort starts fresh.
- **Machine-gun check.** Fires-per-level; many fires = cooldown not biting or the regime should have sat out — flag it. Bands are per-instrument (`Geometry` in `instruments.py`); a mis-scale is fixed on the owning instrument (see tuning section).
- **Cohort status — run the scorecard, don't hand-tally.** `uv run --package trading-scalper trading-scalper-scorecard` — per-(version cohort × instrument root × mode) tally (n / win rate / expectancy + 95% LB / profit factor / max DD / session concentration) + the per-(root, mode) gate verdict. **Cadence:** surface the one-line current-cohort gate status each review; pull the full table + `--chart` deliberately (right after a version bump, or as a mode climbs toward n=50).

**Step 2 — grade the shadow observer (VAP + volume-rate) — SHADOW, gates nothing.** The recorder writes `{date}-tape.jsonl` (raw tape) + `{date}-shadow.jsonl` (POC/value-area + volume-rate). This step only accumulates evidence (`project-scalper-improvements` open #1); it must NOT change Step 1's grades.
- **Contingency table.** For each wall cross: break side = **void** or **HVN** (`VolumeProfile.break_side_read` or rebuilt from tape), and did price **run** or **oscillate**? Add the row(s) to the void→ran / hvn→oscillated table in `project-scalper-improvements` open #1.
- **Volume-rate.** At each cross/fire, expanding or contracting volume (`ratio` >1 / <1)? Note whether expansion lined up with winners — modulator idea, never a fire gate.
- **Stay shadow.** n is tiny; don't over-conclude or wire it in.

**Step 3 — basis drift — SHADOW, gates nothing.** `basis.py` writes `{date}-basis.jsonl` (`{future_price, reference_level, basis}` snapshots). Accumulates the static-offset vs live-cash-space decision (`project-scalper-wall-source`).
- **RTH rows only.** Drop rows whose `reference_level` is unchanged from the prior row (frozen off-hours index). Valid = the contiguous moving-`reference_level` stretch.
- **Report the RTH basis range:** min / max / mean + intraday drift (max − min), one line. Drift ≪ a scalp's few points → keep the static shift; several points → the index-trigger option gets attractive (revisit).
- **Sanity vs carry:** smooth mildly-decaying positive, ~0 near expiry, jumps up at the quarterly roll. A mid-session discontinuity = a roll or an off-hours row that slipped the filter — flag, don't average across it.
- **Stay shadow.**

---

## Tuning the detector — recalibrate a cohort's geometry (periodic, deliberate)

Cross-session, cohort-level — NOT a per-session knob. Do it when review diagnostics (machine-gun, false-break / missed-retest) show a **systematic** band problem across enough samples, or a mode climbing the gate with a visibly mis-scaled band.

**1. Two homes:**
- **Price-distance bands** (`tolerance`, `break_margin`, `min_break_excursion`, `follow_through_margin`, `reentry_margin`, `retest_proximity`, `flip_margin`, `rearm_margin`) → `instruments.py`, on the instrument's `Geometry` (`_SP500_GEOMETRY` for /MES,/ES; `_NASDAQ_GEOMETRY` for /MNQ,/NQ). Fix on the owning instrument only.
- **Time windows** (`cooldown_s`, `confirm_s`, `failure_window_s`, `retest_window_s`, `gap_s`, `window_s`) → `detector.py` / `breakout.py` defaults. These apply across instruments — weigh against every cohort.

**2. Symptom → knob:**

| Review symptom | Likely knob | Direction |
|---|---|---|
| Machine-gun: many fires per level on a pin | `tolerance` / `cooldown_s` | narrow / lengthen |
| `break` fires then round-trips (false breaks graded losses) | `break_margin` / `min_break_excursion` | widen |
| `retest` never fires though break-and-pullback happened | `retest_window_s` / `retest_proximity` | lengthen / widen |
| `reversal` fires on what became a real trend | `failure_window_s` | shorten |
| Flip tripwire chatters on noise | `flip_margin` | widen |

**3. Discipline — spawn a fresh cohort for what changed:**
- **Shared-logic change** (`detector.py` / `breakout.py` / time windows / bracket / arming) → bump `version.py` `__version__`. Resets **all** roots.
- **One instrument's geometry** (`instruments.py`) → should reset only that root. The per-instrument geometry-generation stamp is deferred; until it exists, tuning the only instrument with data (/MES) can bump the global version. Once /MNQ has a live cohort, build the stamp *before* tuning either.

Corollary: **tune in a batch, not knob-by-knob** — every reset restarts the climb to n≥50 / ≥10 sessions. Log the change + rationale in `project-scalper-verdict-calibration`, then re-run the scorecard to confirm the reset.

**Never tune to a single session, and never when the *market* changed** — a regime the map mishandled is a prep problem (wrong `mode`), not geometry. Geometry moves only on a pattern the paper record shows repeatedly.

---

## Mode `check` — thin live snapshot (use sparingly)

Lagging context — the live chart + daemon prompts are the real-time surface. Do not chase.

Call `trading-scalper --basis` (prints the front-month futures price + current carry basis). Add `get_quote <reference>` for cash context. Compare the futures price against the level map. For /MES VWAP / structure read the daemon's shadow snapshot (`~/.trading/scalp/paper/{date}-shadow.jsonl`, latest POC/value-area) or the live chart. Output 3 lines max:
- **Price vs VWAP** (side + slope) + distance to the nearest mapped edge.
- **Recent volume** (expanding into a move = real; fading = suspect).
- **One verdict:** "at an edge — setup (level/target/stop)" OR "middle of range — no trade" OR "trigger fired: [what]."

Mid-range → the only answer is "no trade, wait."

---

*v1. If scalping matures across sessions, extract the framework + regime playbook into `docs/scalping-playbook.md` and reference it here.*
