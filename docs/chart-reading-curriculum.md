# Chart Reading & Market Data — A Learning Curriculum

A self-study path for reading price charts and intraday data, sequenced for the
two horizons actually traded here: **intraday SPY/QQQ 0–1DTE scalps** (the
[`trading-scalper`](scalper-automation.md) / [`/scalp`](../.claude/commands/scalp.md)
domain) and **swing/position option entries** (the
[decision-framework](decision-framework.md) domain).

The bias is deliberate: most of the leverage is in **intraday microstructure**,
because that is where the scalper operates and where the documented QQQ losses
came from (no stops, chasing — memory `project-qqq-scalping`). The scalper already
*encodes* much of what follows (gamma walls, zero-gamma flip, fade-vs-break
geometry, tape aggressor side); learning to read these by eye makes you a better
operator of your own system and a better judge of when to override it.

**Discipline framing, up front.** Per the decision-framework: *"technicals only
refine timing within an already-approved trade."* Fundamentals decide *what* to
trade; charts decide *when*. Oscillators (Layer 4 below) are where beginners
overfit — consult them last, not first.

---

## The mental model — a chart answers four questions

Don't learn "indicators." Learn the four things price encodes; indicators are just
lenses on them.

| Layer | The question | What to read | Stack tools that touch it |
|---|---|---|---|
| **1. Structure** | Where is price, trending or ranging? | Candlesticks (OHLC), support/resistance & supply/demand zones, market structure (HH/HL vs LH/LL), trendlines | `get_technical_indicators`, `get_tradier_history` |
| **2. Participation** | Is the move real — who's behind it? | Volume bars (confirm vs diverge), **VWAP** (institutional anchor), relative volume (RVOL) | `get_vwap`, `get_anchored_vwap` |
| **3. Volatility / range** | How far can it travel today? | ATR, Bollinger Bands, **expected move**, IV vs HV | `get_expected_move`, `get_iv_metrics` |
| **4. Momentum** | Accelerating or tiring? *(secondary — timing only)* | RSI, MACD | `get_technical_indicators` |

Read top to bottom. Most "the chart looks bullish" mistakes are someone reading
Layer 4 (an oscillator) before Layer 1 (structure).

---

## Layer 5 — intraday microstructure (the scalper's domain)

The highest-leverage skill for the scalp horizon. Learn in this order:

1. **The tape (time & sales).** Aggressor side: prints lifting the **ask** =
   buyers in control; prints hitting the **bid** = sellers. Read the *balance of
   color*, not that trades happened. The scalper already derives "confirming tape"
   this way — learn to *see* what the bot infers. (`/scalp` Live-layer panel 2 is
   the operational version of this.)
2. **VWAP + the opening range.** The two reference points day-traders anchor to.
   Above/below VWAP is the single most-watched intraday bias; the 9:30–9:45
   opening range sets the day's first edges.
3. **Volume profile / market profile (TPO).** VPOC, value-area high/low. This is
   the *theory behind fade-vs-break*: price rejects the edges of value (fade) or
   accepts beyond them (break). Auction theory is the conceptual parent of the
   plan's per-level `mode`.
4. **Gamma levels.** Call wall / put wall / zero-gamma flip. `get_gamma_profile`
   computes these; overlaying them on the chart is the manual version of what
   `/scalp prep` writes into the session plan. Watch how price magnetizes to walls
   in +GEX and accelerates through them in −GEX.
5. **Level 2 / DOM (the depth ladder).** Resting size, absorption, eaten-vs-pulled
   walls. This is the read no cheap programmatic feed provides — it lives on the
   Webull Premium screen (`/scalp` Live-layer panel 1) and is the gap the bot
   *cannot* close. Worth learning precisely because it's the human's edge over the
   degraded Tradier top-of-book feed.

---

## Resources — filtered (most trading content is noise)

Apply the same filter as the `r/thetagang`-over-WSB split: favor substance, skip
anything selling a system.

**Books — foundations, in order:**

| Book | Author | Covers | Why |
|---|---|---|---|
| *Japanese Candlestick Charting Techniques* | Steve Nison | Layer 1 | The candlestick reference. Start here. |
| *Technical Analysis of the Financial Markets* | John Murphy | Layers 1–4 | The comprehensive lookup. Use as reference, not cover-to-cover. |
| *Mind Over Markets* | James Dalton | Layer 5 (auction/profile) | Makes fade-vs-break *click* conceptually. Most relevant to the scalper. |
| *Trading in the Zone* | Mark Douglas | Discipline | Directly addresses the documented gap — stops, naming the setup. |

**Video / channels — quality-flagged, mapped to the layers:**

| Source | Layer | Note |
|---|---|---|
| **Bookmap** (YouTube + education) | 5 — order flow / DOM | Best free material on the L2/absorption read; *directly* addresses the depth-ladder gap. Start here for microstructure. |
| **SMB Capital** (YouTube) | 5 — tape / structure | Real desk traders; substance, not hype. |
| **SpotGamma / Menthor Q** (YouTube + blogs) | 5 — gamma levels | The manual version of `get_gamma_profile`; watch them trade the same walls the plan writes. |
| **TraderLion / The Chart Guys** | 1–2 — structure/volume | Solid swing-horizon foundations. |
| **TradingView** (charting software) | all | Free tier has candlesticks, VWAP, volume, RSI built in — all you need to start. |

*Skip:* most of FinTwit, anything promising a system, and the ICT rabbit hole
(some useful market-structure vocabulary buried in a lot of overcomplication).

---

## The practice loop — predict, then check against your own data

The fastest way to learn is to make a falsifiable call pre-market, then grade it
against data you already pull. This *is* the `/scalp prep` → session → `/scalp
review` cycle, used as a learning instrument:

1. **Pre-market.** Run `/scalp prep` (or `get_gamma_profile QQQ` +
   `get_market_regime`). Mark the call wall, put wall, and zero-gamma flip on a
   TradingView QQQ chart. Write **one falsifiable sentence**: *"+GEX, so I expect
   the walls to hold → fade back to VWAP."*
2. **Intraday.** Watch price interact with those levels. Did it reject (fade) or
   punch through (break)? Was VWAP support or resistance? Note it — don't trade it
   while learning.
3. **End of day.** Pull `get_timesales` around the levels and compare the tape to
   what you thought you saw. After a paper week, the scalper's
   `~/.trading/scalp/paper/{date}-signals.jsonl` (B4 telemetry) is a *labeled
   dataset* — read the winners vs losers and you'll learn which tape conditions
   actually mattered, empirically rather than by gut.

The loop's value is the **falsifiable sentence** in step 1: it turns watching into
a graded prediction. Over weeks, `/scalp review`'s diagnostics (win/loss size
asymmetry, chase count, middle trades) become your scorecard.

---

## A four-week start

| Week | Focus | Deliverable |
|---|---|---|
| **1** | Layer 1 — candlesticks + structure. Read Nison §1–6; mark daily S/R + trend on QQQ/SPY by hand. | Can label HH/HL vs LH/LL and name three S/R levels on a daily chart. |
| **2** | Layers 2–3 — VWAP, volume, ATR/expected move. Overlay VWAP intraday; cross-check `get_expected_move`. | Can state the day's expected range and whether price is above/below VWAP and why it matters. |
| **3** | Layer 5 — tape + gamma. Bookmap intro series; run the practice loop daily (predict → check). | One falsifiable pre-market call per day, graded at the close. |
| **4** | Integrate — paper-trade the loop with the scalper running. | A paper week of `{date}-signals.jsonl` + a `/scalp review` read on which conditions separated winners from losers. |

Momentum oscillators (Layer 4) are intentionally *not* a focus week — they're the
last refinement, not a foundation.

---

*Companion to [scalper-automation.md](scalper-automation.md) and the
[`/scalp`](../.claude/commands/scalp.md) skill. Charts decide timing within an
already-approved trade; the thesis and the stop still do the real work.*
