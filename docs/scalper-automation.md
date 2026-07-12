# Scalper Automation — Local Paper Entry-Detector

A standalone session-scoped app that **detects an intraday index-futures scalp
setup, prompts you to enter, and paper-trades the same direction-aware bracket**
— so the detector accumulates a reviewable track record before it is ever trusted
with real capital.

The traded instrument is **/MES (Micro E-mini S&P 500)** — $5/point, 0.25 tick,
right-sized for paper/learning; the registry (`instruments.py`) also carries /ES
($50/pt), /MNQ ($2/pt), and /NQ ($20/pt), a one-line swap away. Futures fit a
level-based index scalper the way 0DTE options never did: **linear $/point P&L, no
theta bleed while you wait for a setup, free two-sided direction** (a real
SELL-to-open short, not a long-put proxy), and one instrument that **is** the level
map. (Migrated from SPY/QQQ 0DTE options 2026-07-12 — see the pivot note below.)

This is the executable counterpart to the [`/scalp`](../.claude/commands/scalp.md)
skill: the skill *draws the map* (pre-session levels, lean, day-type, and the
per-level **direction**); this app *watches the map* during the session, points
your eyes at a level the instant price tags it, and forward-tests the trade on
paper. The gamma walls come from **SPX cash-index options** (`get_gamma_profile SPX`
— the deepest, cleanest dealer-gamma pool; ETFs like SPY are out because their
index gap is dividend/tracking noise, not clean carry), already in index points
(~7575), and are **shifted to /MES prices by the live carry basis** — `basis =
/MES − SPX`, pure cost-of-carry (financing − dividends), converging to 0 at expiry
and resetting at the quarterly roll. The basis is *measured*, not modelled: the
daemon streams SPX alongside /MES and records it as a shadow series, and
`trading-scalper --basis` prints it for prep. (SPX + ~50 basis → /MES; **not** a
×10 of SPY.)

> Learning to read the map by eye — tape, VWAP, volume profile, gamma walls, L2 —
> is its own skill: see [chart-reading-curriculum.md](chart-reading-curriculum.md).

## Why this exists (and the two pivots that shaped it)

The original design was an **assist-only stop-enforcer**: it watched for a manual
opening fill and auto-attached a broker-resting stop (`AutoStop`), the "killer
feature." That feature became **redundant** once Webull desktop natively bracketed
an *option* order (a "1st-Trigger Stop": entry + OCO stop-loss / take-profit,
resting at the broker). The broker owned the load-bearing exit job, so the daemon's
value moved to the **entry** — per memory `project-qqq-scalping` the *reads* were
fine; the net loss came from **no stops, chasing, and revenge adds**. What's worth
building is the thing that points your eyes at a blessed level at the right moment,
plus a paper loop that measures whether those prompts actually make money. See
memory `project-scalper-pivot`.

The **second pivot (2026-07-12)** retargeted that same entry-detector from SPY/QQQ
0DTE options onto **/MES futures**. The options wrapper was a poor fit for a level
scalper — theta bled while waiting, only partial delta was captured, "short" meant
buying a put, and P&L was non-linear. Futures make the bracket a clean, linear,
two-sided $/point instrument, and the traded symbol *is* the level map. The
migration **replaced** the options path (git-recoverable, mirroring how the first
pivot removed `AutoStop`/`WebullBroker`) rather than parameterizing both — one
instrument, one code path. The hexagonal ports (`MarketDataFeed` +
`BrokerExecution`) and the `Ledger` cost-basis math were already instrument-agnostic
and needed no change; the work concentrated in three seams — bracket semantics,
detector geometry, and a net-new DXLink feed.

## The three goals

1. **Prompt** — detect when /MES tags one of the morning's blessed levels
   (filtered by the plan's `lean`, annotated with tape direction) and fire a desk
   alert: *enter here.*
2. **Auto-execute on paper** — on every prompt, place the *same* direction-aware
   bracket (entry at market + child stop-loss + take-profit, OCO) in an in-memory
   `PaperBroker`.
3. **Persist for review** — periodically write the paper ledger (fills + realized
   P&L) to disk so a session's detector performance is reviewable afterward, plus a
   per-fire **B4 velocity/absorption telemetry** log (recorded, not gated) so the
   run can later learn which setup conditions separate winners from losers.

## Safety model: paper-only

There is **no live-order path**, and there is **no real futures account** — going
live is a future tier that must be earned by a long paper track record. The old
load-bearing invariant (`RiskReducingOnly` — the daemon may submit only
risk-reducing orders) is deliberately gone: the daemon now *opens* positions, which
that invariant forbade. The new safety story is simpler and absolute — **it is all
paper, zero real capital at risk.**

## Two ports, not one

Data source and execution are **independent**. Tastytrade's DXLink is the *data
feed*; the `PaperBroker` is the *executor*. (No real broker is involved — there is
no futures account, and the daemon auto-executes on paper.)

```python
class MarketDataFeed(Protocol):          # where prices come from
    async def subscribe(self, symbols: list[str]) -> None: ...
    def on_quote(self, cb): ...          # top-of-book bid/ask + sizes
    def on_trade(self, cb): ...          # last prints
    def on_timesale(self, cb): ...       # the tape

class BrokerExecution(Protocol):         # orders out + order events in
    def place(self, order: Order) -> OrderId: ...
    def cancel(self, id: OrderId) -> None: ...
    def positions(self) -> list[Position]: ...
    def net_position(self, symbol: str) -> int: ...
    def realized_pnl(self) -> float: ...
    def on_order_event(self, cb): ...                 # fills / status changes
```

`PaperBroker` additionally exposes `place_bracket(symbol, direction, quantity, *,
stop_price, target_price, reference=None, tick=0.25)` — the in-memory analog of a
native futures OCO bracket. The entry fills at `direction` (BUY, or **SELL** to open
a real short); the OCO children rest on the **opposite** side at the given absolute
prices, snapped to the instrument tick, and a fill on one cancels the other. Bracket
prices are **absolute /MES prices** resolved upstream by the plan/detector — the
broker stays dumb. P&L is linear: `(exit − entry) × direction × $5/point`, no theta.

### Data-feed reality (read before over-promising the detector)

None of the cheap streaming feeds replicate a full **depth-of-market ladder** the
way a futures DOM does:

- **Tastytrade DXLink** (dxFeed) = top-of-book quote + trade prints + timesale, and
  it unlocks **streaming greeks + IV** later (the roadmap upgrade). It's a token +
  channel handshake: `GET /api-quote-tokens` returns `{token, dxlink-url}`, then a
  DXLink WebSocket walks `SETUP → AUTH → CHANNEL_REQUEST(FEED) → FEED_SETUP →
  FEED_SUBSCRIPTION → FEED_DATA` with a 30 s KEEPALIVE. It reuses the existing
  `[tastytrade]` OAuth creds. **No retail depth ladder.**
- **Webull** TotalView L2 is an **app** entitlement, not cleanly via OpenAPI — and
  it's an equities ladder anyway, not the futures DOM.

So the detector runs on **top-of-book + tape** — a degraded view of a real futures
DOM. It is therefore an **alerter that points the eyes at a pre-mapped level** and
paper-trades it, not (yet) an autonomous live trigger. See memory
`project-scalper-pivot` for the full feed analysis.

## Architecture

```
MarketDataFeed (DXLink WS)
   │  /MES tape — the traded future IS the level map AND the fill source
   ▼
SetupDetector ── price tags a blessed level
   │  filtered by lean + direction, tape-annotated
   ├──▶ Notifier (console + bell)  ── "long /MES here — stop 6294 / target 6308"
   ├──▶ FireRecord ──▶ SignalLog ── per-fire B4 velocity/absorption telemetry JSONL
   └──▶ TradeProposal ──▶ PaperBroker.place_bracket
                              │  fills entry at market + rests OCO stop/target
                              │  order events                    (same /MES tape)
                              ▼
                         PaperPersister ── fills JSONL + periodic P&L summary JSON
```

Each setup is a short paper round-trip: `propose → entry fill → {stop | target}
fill → flat`, with the losing OCO leg auto-cancelled. Because /MES is a single
symbol that is **both** the tape the detector reads and the instrument the bracket
fills against, `drive_paper_fills` routes every print to both the detector and the
matching engine — and a fire is always preceded by the broker-seeding print, so the
bracket never opens blind. The detector fires **once per tag** (hysteresis re-arms
only after price leaves the band), so a hovering price yields one prompt + one paper
bracket, not a spam stream.

## Components

1. **`DxLinkFeed` / `MarketDataFeed`** — wraps `DxLinkStreamClient` (streamer-token
   fetch + DXLink channel handshake + auto-reconnect) and subscribes to the traded
   /MES front-month contract (picked by date via `instruments.front_month`, which
   rolls ~8 days before the quarterly third-Friday expiry) **plus the SPX cash index**
   for the carry-basis shadow; emits quote/trade/timesale. `drive_paper_fills` fans
   every /MES print into the `PaperBroker` matching engine *and* the detector — one
   symbol serves both roles (SPX feeds only the basis shadow).
2. **`SetupDetector` + `Notifier`** — fires only a *confirmed* setup, gated on
   things already on the wire: **geometry** keyed to the level's `mode` (`fade` =
   touch-and-reject within the band, the +GEX trade; `break` =
   cross-the-wall-with-follow-through, the −GEX trade), **lean** (on the trade
   *direction* — a long needs `long-only`/`both`, a short `short-only`/`both`), and
   for `fade`/`break` **tape** (the print aggressor must agree with the trade
   direction; the `reversal`/`retest` verdict modes gate on **geometry + lean only,
   never tape**). On a confirmed fire it `notify`s the human (console line + bell)
   and, for a level carrying a `direction`, resolves the bracket's absolute
   stop/target prices and emits a `TradeProposal`; a confirmed-but-inverted bracket
   or a wide book still alerts but is not paper-filled (honest fills). A
   **`direction`-less level is alert-only** (no paper trade). Underlying top-of-book
   size imbalance is a soft annotation, never a gate.
   A **break** level additionally **arms** only after the detector has *witnessed*
   price on the pre-break side (below a resistance breakout, above a support
   breakdown): a break is a one-time edge event, but the geometry gate alone reads
   "price is currently across the level" — true for the whole extended move — so a
   cold start (or re-arm) with price already past the level stays silent until price
   comes back and crosses again. The **wake guard** backs this up: a long gap between
   print timestamps (`gap_s`, default 90 s) means the stream was
   suspended/disconnected (laptop sleep), so all arming + fired state is dropped —
   every break level must re-witness its setup side before it can fire. Together
   these stop a daemon that slept through the actual cross from waking up and firing
   at the extended top. Fade levels need no arming — they re-test their level all
   session and self-correct. The `reversal` (failed break → trade the snap-back) and
   `retest` (confirmed break → trade the pullback-and-resume) verdicts are driven by
   a per-wall `BreakoutTracker` (`breakout.py`).
3. **`PaperBroker.place_bracket`** — opens at market in the proposed `direction` and
   rests an OCO stop-loss + take-profit pair at the **absolute** stop/target prices
   (tick-snapped). For a long the children rest on the SELL side (stop below, target
   above); for a short they rest on the BUY side (stop above, target below). Position
   + realized P&L are computed by the `Ledger` cost-basis primitive (the single
   place the math lives), linear at $5/point for /MES.
4. **`PaperPersister`** — subscribes to the broker's order events; appends each fill
   to `~/.trading/scalp/paper/{date}.jsonl` and rewrites a `{date}-summary.json`
   (realized P&L + open positions) on a timer and once on shutdown.
5. **`SignalLog`** — the detector's `record` sink; appends one row per *confirmed
   fire* to `~/.trading/scalp/paper/{date}-signals.jsonl` carrying the **B4
   velocity/absorption telemetry** (trailing-window velocity in $/s, cumulative
   confirming vs contrary tape size, top-of-book imbalance) next to the setup
   identity. **Recorded, never a gate** — separate from the fills log on purpose, so
   an alert-only or spread-suppressed fire (no paper fill) is still captured. The
   paper run mines these against the realized win/loss to learn which metrics
   actually separate winners from losers *before* any of them is allowed to veto a
   setup.
6. **Shadow observers (`ShadowRecorder`, `BasisRecorder`)** — pure telemetry wired
   onto the tape, **read by nothing in the decision path** (`feedback_shadow_then_live`).
   `ShadowRecorder` captures the raw /MES tape + live volume-profile / volume-rate
   snapshots (`{date}-tape.jsonl` + `{date}-shadow.jsonl`) to settle the runaway-gap
   question from evidence. `BasisRecorder` tracks the live `/MES − SPX` carry basis
   (`{date}-basis.jsonl`) so the later choice — bake a per-session offset into the map
   vs. track basis live in the detector's geometry — rests on recorded data.
   **Basis rows are valid RTH only** (SPX computes only while its components trade;
   off-hours the future has drifted against a stale cash close). Both gate nothing.

## The `/scalp` handoff — the session plan (daily file)

The detector needs the morning's **blessed levels** in structured form, each naming
the **direction** to trade if it tags. A plan is valid for one day, so it's a dated,
hand-editable flat file:

`~/.trading/scalp/{date}-{key}.yaml`   (`{key}` = the plan symbol's root, e.g. `MES`)

```yaml
date: 2026-07-12
symbol: "/MESU26:XCME"       # the dxFeed streamer symbol — what the feed subscribes + fills
regime: fragile-pin          # pin | fragile-pin | breakout-trend  (GEX sign)
lean: both                   # long-only | short-only | both | no-trade
contracts: 1                 # quantity per setup
default_stop_points: 6.0     # child stop-loss offset from the fill (points)
default_target_points: 8.0   # child take-profit offset from the fill (points)
zero_gamma: 7625.0           # the gamma flip (SPX 7575 + basis 50) — tripwire, alerts on a cross
levels:                      # /MES prices (SPX gamma walls + carry basis) + the direction to trade
  # +GEX → fade: put wall (support) → long, call wall (resistance) → short
  - {price: 7600.0, side: support,    direction: long,  mode: fade}
  - {price: 7675.0, side: resistance, direction: short, mode: fade}
notes: "Fragile pin: fade the walls to the zero-gamma flip; a break of it = trend, stop fading"
```

- `levels` are **/MES prices** (the GEX **walls** from `get_gamma_profile SPX`, each
  **+ the carry basis** from `trading-scalper --basis`) that drive the detector. Each `mode` picks the trigger geometry —
  `fade` / `break` / `reversal` / `retest` — and `direction` (`long` | `short` |
  omitted) is the side to trade when it triggers. **There is no contract / strike /
  expiry / OCC step — the future itself is the instrument.** Optionally set explicit
  `stop`/`target` /MES prices per level; otherwise `default_stop_points` /
  `default_target_points` derive them from the fill (stop below a long / above a
  short, target the mirror). `level.stop` is **load-bearing** — the real paper stop,
  not alert-text — and each point = $5.
- `zero_gamma` is the **gamma-flip tripwire** (one /MES price, not a level). The
  detector watches /MES cross it in *either* direction and fires a *non-trading*
  "the regime may be inverting — re-run `/scalp prep`" alert; it proposes no trade.
  It is the cheap mitigation for the top residual risk — a stale regime label
  (yesterday's OI) feeding each level's `mode`, so the bot fades a level that's
  actually breaking. The detector **never recomputes GEX** (the stream has no
  OI/greeks); the flip stays the static prep-time number, so a cross means
  *reassess*, not an automatic fade↔break switch. Omit it (or set null) to disable
  the tripwire.
- The daemon loads today's file on launch and **hot-reloads on change** (re-run
  `/scalp prep` and edited levels/lean/mode are picked up). **Caveat:** the subscribe
  list is fixed at startup, so switching to a *new* futures contract mid-session
  needs a restart.
- **Missing file = graceful degrade:** no plan → the detector is silent (no prompts,
  no paper trades). A level with no `direction` → alert-only.
- `/scalp prep` **writes this file** — it reads the regime + gamma walls from
  `get_gamma_profile SPX`, sets each level's `mode` from the GEX sign, shifts the
  walls to /MES by the live carry basis (`trading-scalper --basis`), assigns a
  `direction` per wall (mode-correct), and emits the YAML; the file stays
  hand-editable to nudge an edge before the open.

This is the seam: **skill draws the map → `~/.trading/scalp/*.yaml` → daemon watches
the map and paper-trades it.**

## Runtime & lifecycle

**Not a daemon — a session-scoped foreground app.** Start it from a terminal
(`uv run --package trading-scalper trading-scalper`); it streams the tape, prompts +
paper-trades through the session, and you Ctrl-C at the close. **POSIX-first
(Linux + macOS).**

- **Single asyncio loop.** One feed connection, one paper broker, and the persister +
  shadow + basis recorder tasks (`asyncio.gather(feed.run(), persister.run(),
  shadow.run(), basis.run())`). Each flushes a final write on shutdown.
- **Feed resilience.** WS auto-reconnect with exponential backoff, a fresh streamer
  token per reconnect, and re-subscribe on drop; a 401/403 on the token fetch (a
  bad/expired Tastytrade OAuth token) is treated as fatal, not retried.
- **Clock.** Session windows are ET-anchored via `zoneinfo`, independent of the
  machine's local timezone.
- **Offline demo.** `--demo-setup SYMBOL[:QTY[:PRICE]]` (e.g. `--demo-setup
  /MES:1:6300`) injects one long setup, fills the direction-aware bracket, writes a
  summary, and exits — no network, no Tastytrade creds needed, for smoke-testing the
  loop.
- **Basis query.** `--basis` streams the front-month /MES + SPX briefly, prints the
  live carry basis, and exits — the prep helper for shifting SPX walls to /MES.
  `--reference SYMBOL` picks the cash index (default `SPX`); `--reference ''` disables
  the basis shadow.

## Monorepo placement

Package `packages/trading-scalper/`, depends on `trading-clients[streaming]` +
`pyyaml`. The streaming transport (`dxlink_stream_client.py`) and the
provider-neutral `market_stream.py` value types live in `trading-clients`.

```
trading-clients (httpx[http2]; + websockets via [streaming] extra)
  ├── trading-mcp        (+ fastmcp + yfinance)
  ├── trading-alerts     (+ boto3 + pynacl)
  └── trading-scalper    (+ pyyaml)
```

## Versioning & the go-live scorecard

Going live is **earned per verdict mode**, on the numbers — not on a feeling that
"the bot looks ready." Two pieces make that objective.

**Version cohorts (`version.py`).** The detector carries a `major.minor.patch`
version. A **minor** bump means the change alters what/when/how it trades (arming
rules, verdict logic, calibration constants, gates, bracket placement); a **patch**
bump is observer-only (telemetry, logging, persistence). `SignalLog` stamps the
version on every fire row, so each session's logs self-describe which bot produced
them. The **cohort** is `major.minor`: grading pools only trades from the same
behavior cohort, because a change to the trading logic makes earlier trades evidence
about a bot that no longer exists. The **futures migration ships as `0.4.0`** — a
fresh cohort, so /MES fires are never pooled with the SPY/QQQ options track record
(`0.3`). Bump in the same commit as the behavior change so the stamp can't drift
from the code. Sessions that predate versioning (before `0.3.1`, shipped
2026-07-10) are mapped to a cohort by date in `scorecard._RETRO_COHORTS`.

**The scorecard (`scorecard.py`, `trading-scalper-scorecard`).** Reconstructs closed
trades by joining the fills log to `{date}-signals.jsonl` on `bracket_id` (a closed
trade = a bracket with a closing exit; P&L = the exit's `realized_delta`), buckets
them by `(cohort, mode)`, and reports n, sessions, win rate, expectancy,
expectancy's one-sided 95% lower bound, profit factor, max drawdown, and **session
concentration** (the best single session's share of gross wins — the guard against a
"one good day carries the mode" edge). A pooled all-history line shows as a floor
("has this ever worked"), never as the promotion basis. `--chart` writes a per-mode
cumulative-P&L curve with dashed cohort-boundary markers (a slope kink at a ship is
the improvement verdict — readable where a daily win-rate bar is just noise).

**The go-live gate** is evaluated on the **current cohort only**: `n ≥ 50` across
`≥ 10` sessions, profit factor `≥ 1.5`, expectancy lower bound `> 0`, concentration
`< 40%`. When a mode passes, the promotion is a git tag on that commit
(`scalper-vX.Y.Z`); the future live runner deploys from the tag while paper keeps
running the workspace head, and the version stamp keeps the two track records
attributable. The `0.4` futures cohort **starts empty** — nothing has passed, and
the geometry constants (rescaled ~×10 from the QQQ originals) are a first cut pending
recalibration against real /MES tape.

**Caching.** Past sessions are immutable, so the scorecard caches each pre-*today*
session's extracted trades in `~/.trading/scalp/paper/scorecard-cache.json` (keyed by
date; today's still-appending session is always re-parsed). The cache stores the raw
version stamp, not the resolved cohort — so re-tuning the retro map or the gate never
invalidates it. It rides the scalp prefix in `env_sync` for free (whole-directory
sweep) and its dateless name keeps the retention archiver from ever gzipping it.

## Roadmap (deferred)

- **Tastytrade greeks feed / on-the-future gamma** — the DXLink client already streams
  quote/trade/timesale; adding live delta/gamma/theta/vega + IV is a matter of
  subscribing the `Greeks` event type and slotting a new neutral value type alongside
  `Quote`/`Trade`/`TimeSale`. Tastytrade *does* expose ES/MES futures options
  (`/futures-option-chains/:product/nested` → streamer symbols; `Greeks` carries
  per-strike gamma, `Summary` carries `openInterest`), so a **zero-basis gamma map on
  the future itself** is buildable — but deliberately deferred: it only removes a basis
  we already measure live, ES-option gamma is a smaller/different pool than the
  dominant SPX 0DTE gamma, and it needs a streaming-assembler (gamma + OI aren't in any
  REST payload). SPX-walls + live-basis stays the source; this is the enabler for a
  later ES cross-check.
- **Live cash-space geometry** — instead of baking a per-session basis into the map,
  run the detector's geometry in SPX-cash space and convert /MES↔SPX live off the
  recorded basis. Decide between this and the static baked offset once
  `{date}-basis.jsonl` has separated the two on real RTH tape.
- **Native /MES levels** — overnight H/L, Globex range, futures VWAP, prior settle,
  sourced from DXLink `Candle` events (`/MESU26:XCME{=1m}` + `fromTime`). A fourth,
  non-gamma level source; `BreakoutTracker` is already level-source-agnostic so they
  plug in as `reversal`/`retest` rows.
- **Phone-push notifier** — reuse the `trading-alerts` Discord bot to land prompts on
  your phone. v1 is desk-only console + bell.
- **Autonomous entry (live)** — only after a verdict mode passes the go-live gate
  above. This re-introduces a live futures broker that *opens* and a real
  risk-budget. Out of scope until the scorecard earns it. See memory
  `project-scalper-pivot` / `project-scalper-grpc-events`.

---

*v3. Paper-only entry-detector. Pivoted from the assist-only stop-enforcer
2026-06-12 (Webull's native option bracket made `AutoStop` redundant), then migrated
from SPY/QQQ 0DTE options to /MES index futures 2026-07-12; the level map now sources
gamma walls from SPX cash-index options (no ETF) shifted to /MES by a live-measured
carry basis, not a ×10 of SPY. Safety property: no real capital is ever at risk.*
