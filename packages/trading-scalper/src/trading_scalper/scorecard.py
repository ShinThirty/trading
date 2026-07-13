"""Grade the paper detector's track record — per behavior cohort × instrument × mode.

The daemon writes a joinable dataset (``persist.py``): every fire lands a features
row in ``{date}-signals.jsonl`` and every fill a row in ``{date}.jsonl``, joined on
``bracket_id`` with the close's ``realized_delta`` as the win/loss label. This module
turns that into a scorecard that answers the only question that matters before going
live: **has a given verdict mode, on a given instrument, in the CURRENT bot version,
earned promotion?**

Why cohorts. A change to the detector's trading logic makes earlier trades evidence
about a bot that no longer exists, so pooling all history would let a since-replaced
version's good days buy a promotion. Trades are grouped by **behavior cohort**
(``version.cohort_of`` = ``major.minor``): sessions self-describe their cohort via the
``version`` stamp on each signal row; sessions that predate the stamp are mapped by
date from ``_RETRO_COHORTS`` (git evidence in the comments there). Cohort resolution
lives here in code, not in the cache — so re-tuning the retro map or the gate never
invalidates a cached extraction.

Why the instrument dimension. Since the detector generalized past /MES (per-instrument
``Geometry`` + cash-index ``reference``), the same version runs different price maps on
/MES vs /MNQ — so their fills must NOT pool: one instrument's record can't buy the
other's promotion. Trades additionally group by instrument **root** (``root_of`` →
``/MES``), taken from the traded symbol on the fill; keying on the root (not the dated
contract) keeps a quarterly roll from splitting a cohort. The gate is per (root, mode),
so promotion (git-tag → live) is granular — /MES clearing a mode never green-lights
/MNQ. (A per-instrument *geometry* re-tune must reset only its own root's cohort; that
needs a geometry-generation stamp, deferred until a second instrument's cohort exists —
today all roots share one generation, so root + version suffice.)

The go-live gate (``Gate``) is evaluated on the CURRENT cohort only; older cohorts
render as history. A pooled all-history line is shown as a floor ("has this ever
worked"), never as the promotion basis.

Cache. The expensive step is parsing every historical log — which grows worse once
retention gzips old sessions in place (``env_sync.py``). Past sessions never change,
so extracted trades for any session before *today* are cached in
``scorecard-cache.json`` (keyed by session date) and reused. The cache stores the raw
``version`` stamp, not the resolved cohort, so cohort/gate policy stays editable. It
lives under the scalp prefix, so ``env_sync`` carries it across machines for free (a
whole-directory sweep) and its name has no leading date, so the archiver never gzips
it.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import os
import statistics
import sys
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from trading_clients.table_helpers import list_table

from trading_scalper.instruments import root_of
from trading_scalper.version import __version__, cohort_of

PAPER_ROOT = Path.home() / ".trading" / "scalp" / "paper"
CACHE_NAME = "scorecard-cache.json"
SCHEMA_VERSION = 2  # bump to discard + rebuild the cache when the extraction format changes

# One-sided 95% normal quantile — the multiplier on the standard error for the
# lower confidence bound on expectancy (mean - Z * s/sqrt(n)).
Z_95 = 1.645

# Stable display order for verdict modes; "?" = a closed bracket whose fire row was
# missing (no signals join), surfaced rather than silently dropped.
_MODE_ORDER = ["break", "fade", "reversal", "retest", "?"]

# Retro cohort map for sessions that predate the version stamp (version.py shipped
# 2026-07-10 as 0.3.1). A session's cohort is the last entry whose start date is <=
# the session date. Stamped sessions ignore this map entirely — the stamp wins.
#   0.1  bracket-dataset era (0f04400, 6/14) — no closed trades exist before 6/15
#   0.2  downtime-safe break arming (023cb54, 6/15)
#   0.3  verdict modes + re-fire cooldown (6790c25 / 1980037, 6/23);
#        the 6/29 shadow-telemetry ship (f1606bc) was observer-only → still 0.3
_RETRO_COHORTS: list[tuple[date, str]] = [
    (date(2026, 1, 1), "0.1"),
    (date(2026, 6, 15), "0.2"),
    (date(2026, 6, 23), "0.3"),
]


@dataclass(frozen=True)
class ClosedTrade:
    """One closed paper bracket: its win/loss label plus what's needed to bucket it.

    ``version`` and ``symbol`` are the raw stamps off the log rows; the cohort and the
    instrument *root* are resolved from them at read time (``resolve_cohort`` /
    ``resolve_root``) so cached rows survive a change to grouping policy. ``symbol`` is
    the dated streamer symbol that traded (``/MESU26:XCME``); it resolves to a root
    (``/MES``) for grouping — the roll doesn't split the cohort.
    """

    session: str  # YYYY-MM-DD (the log file's date key)
    ts: str  # wall-clock of the closing fill — chronological sort key
    bracket_id: str
    mode: str  # break | fade | reversal | retest | "?"
    version: str | None  # raw stamp, or None if the session predates versioning
    pnl: float
    symbol: str | None = None  # traded streamer symbol; None on a pre-symbol-dimension row

    def as_cache_row(self) -> dict[str, object]:
        return {
            "ts": self.ts,
            "bracket_id": self.bracket_id,
            "mode": self.mode,
            "version": self.version,
            "pnl": self.pnl,
            "symbol": self.symbol,
        }


def resolve_root(symbol: str | None) -> str:
    """Instrument root for a trade: its symbol's root, or ``"?"`` when unstamped."""
    return root_of(symbol) if symbol else "?"


def resolve_cohort(session: str, version: str | None) -> str:
    """Cohort key for a trade: its stamped version if present, else the retro date map."""
    if version:
        return cohort_of(version)
    d = date.fromisoformat(session)
    cohort = _RETRO_COHORTS[0][1]
    for start, name in _RETRO_COHORTS:
        if d >= start:
            cohort = name
    return cohort


def current_cohort() -> str:
    """The cohort the running detector belongs to — the one the go-live gate judges."""
    return cohort_of(__version__)


# ── extraction ──────────────────────────────────────────────────────────────


def _read_jsonl(base: Path) -> list[dict]:
    """Parse a JSONL log, transparently reading ``base`` or its ``.gz`` archive.

    Retention gzips old sessions in place (``env_sync.py``); a plain and a gzipped
    copy can briefly coexist, so the uncompressed file wins. Returns [] if neither
    exists. Blank/partial tail lines (from a hard kill) are tolerated.
    """
    gz = base.with_name(base.name + ".gz")
    if base.exists():
        text = base.read_text()
    elif gz.exists():
        text = gzip.decompress(gz.read_bytes()).decode("utf-8")
    else:
        return []
    rows = []
    for line in text.splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def extract_session(root: Path, session: str) -> list[ClosedTrade]:
    """Extract closed trades for one session by joining its fills log to its signals log.

    A closed trade is a bracket with at least one SELL fill (the exit); its P&L is the
    sum of ``realized_delta`` over the bracket's fills (0 on the BUY open, the close's
    dollars on the SELL exit) — so a $0 scratch exit counts as a closed trade, not an
    open. Mode + version + symbol come from the fire's signals row, joined on
    ``bracket_id``; a bracket with no matching fire row is labeled mode ``"?"`` and root
    ``"?"`` rather than dropped. The signals ``symbol`` is the fire's *instrument* — the
    underlying in the options era (``QQQ``), the future in the futures era
    (``/MESU26:XCME``) — which resolves to a clean root; the fills ``symbol`` is the
    literal OCC contract, which would shatter the options cohorts per strike, so it's
    deliberately not the grouping source.
    """
    fills = _read_jsonl(root / f"{session}.jsonl")
    signals = _read_jsonl(root / f"{session}-signals.jsonl")

    meta: dict[str, tuple[str, str | None, str | None]] = {}
    for row in signals:
        bid = row.get("bracket_id")
        if bid is not None and bid not in meta:
            meta[bid] = (row.get("mode", "?"), row.get("version"), row.get("symbol"))

    pnl: dict[str, float] = defaultdict(float)
    closed: set[str] = set()
    close_ts: dict[str, str] = {}
    for row in fills:
        bid = row.get("bracket_id") or row.get("order_id")
        if bid is None:
            continue  # a fill with no id can't be attributed to a bracket
        delta = row.get("realized_delta")
        if delta is not None:
            pnl[bid] += delta
        if row.get("side") == "SELL":
            closed.add(bid)
            close_ts[bid] = row.get("ts", "")

    trades = []
    for bid in closed:
        mode, version, symbol = meta.get(bid, ("?", None, None))
        trades.append(
            ClosedTrade(
                session=session,
                ts=close_ts.get(bid, ""),
                bracket_id=bid,
                mode=mode,
                version=version,
                pnl=round(pnl[bid], 2),
                symbol=symbol,
            )
        )
    trades.sort(key=lambda t: t.ts)
    return trades


def _session_dates(root: Path) -> list[str]:
    """All session dates with a fills log (plain or gzipped), ascending."""
    dates: set[str] = set()
    for p in root.glob("????-??-??.jsonl*"):
        name = p.name
        if name.endswith("-signals.jsonl") or name.endswith("-summary.json"):
            continue
        stem = name[:10]
        try:
            date.fromisoformat(stem)
        except ValueError:
            continue
        # Only fills logs: {date}.jsonl / {date}.jsonl.gz (not {date}-tape.jsonl etc.)
        rest = name[10:]
        if rest in (".jsonl", ".jsonl.gz"):
            dates.add(stem)
    return sorted(dates)


# ── cache ───────────────────────────────────────────────────────────────────


def _load_cache(path: Path) -> dict[str, list[ClosedTrade]]:
    """Read the extraction cache; empty on absence, unreadable data, or a schema mismatch."""
    if not path.exists():
        return {}
    try:
        blob = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    if blob.get("schema") != SCHEMA_VERSION:
        return {}  # format changed — rebuild from the logs
    out: dict[str, list[ClosedTrade]] = {}
    for session, rows in blob.get("sessions", {}).items():
        out[session] = [
            ClosedTrade(
                session=session,
                ts=r["ts"],
                bracket_id=r["bracket_id"],
                mode=r["mode"],
                version=r.get("version"),
                pnl=r["pnl"],
                symbol=r.get("symbol"),
            )
            for r in rows
        ]
    return out


def _write_cache(path: Path, sessions: dict[str, list[ClosedTrade]]) -> None:
    """Atomically persist the cache (temp file + os.replace, so a sync can't read a torn file)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    blob = {
        "schema": SCHEMA_VERSION,
        "sessions": {s: [t.as_cache_row() for t in trades] for s, trades in sessions.items()},
    }
    tmp = path.with_name(path.name + f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(blob, indent=2) + "\n")
    os.replace(tmp, path)


def load_closed_trades(
    root: Path = PAPER_ROOT,
    *,
    today: date | None = None,
    use_cache: bool = True,
    _extract: Callable[[Path, str], list[ClosedTrade]] = extract_session,
) -> list[ClosedTrade]:
    """Load every closed trade, using (and refreshing) the per-session extraction cache.

    Sessions strictly before ``today`` are immutable, so their extracted trades are
    cached and reused; today's still-appending session is always re-parsed live.
    ``_extract`` is injectable for tests to count real parses. Returns trades sorted
    chronologically by session then close time.
    """
    today = today or date.today()
    cache_path = root / CACHE_NAME
    cache = _load_cache(cache_path) if use_cache else {}

    all_trades: list[ClosedTrade] = []
    dirty = False
    for session in _session_dates(root):
        is_past = date.fromisoformat(session) < today
        if use_cache and is_past and session in cache:
            all_trades.extend(cache[session])
            continue
        trades = _extract(root, session)
        all_trades.extend(trades)
        if use_cache and is_past:
            cache[session] = trades
            dirty = True

    if use_cache and dirty:
        _write_cache(cache_path, cache)

    all_trades.sort(key=lambda t: (t.session, t.ts))
    return all_trades


# ── stats ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ModeStats:
    cohort: str
    root: str  # instrument root (/MES, /MNQ, …); "ALL" for the pooled floor
    mode: str
    n: int
    sessions: int
    win_rate: float  # fraction in [0, 1]
    total: float
    expectancy: float  # mean $/trade
    expectancy_lb: float | None  # one-sided 95% lower bound; None when n < 2
    profit_factor: float  # gross wins / gross losses; inf if no losses
    max_drawdown: float  # most-negative peak-to-trough on the equity curve (<= 0)
    concentration: float | None  # best session's share of gross wins; None if no wins


def _stats_for(cohort: str, root: str, mode: str, trades: list[ClosedTrade]) -> ModeStats:
    pnls = [t.pnl for t in trades]
    n = len(pnls)
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gross_win = sum(wins)
    gross_loss = -sum(losses)

    expectancy = statistics.mean(pnls)
    expectancy_lb = None
    if n >= 2:
        sd = statistics.stdev(pnls)
        expectancy_lb = round(expectancy - Z_95 * sd / math.sqrt(n), 2)

    if gross_loss > 0:
        profit_factor = round(gross_win / gross_loss, 2)
    else:
        profit_factor = math.inf  # no losing trades

    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in pnls:  # trades already chronological within (cohort, mode)
        equity += p
        peak = max(peak, equity)
        max_dd = min(max_dd, equity - peak)

    per_session_win: dict[str, float] = defaultdict(float)
    for t in trades:
        if t.pnl > 0:
            per_session_win[t.session] += t.pnl
    concentration = round(max(per_session_win.values()) / gross_win, 3) if gross_win > 0 else None

    return ModeStats(
        cohort=cohort,
        root=root,
        mode=mode,
        n=n,
        sessions=len({t.session for t in trades}),
        win_rate=round(len(wins) / n, 3),
        total=round(sum(pnls), 2),
        expectancy=round(expectancy, 2),
        expectancy_lb=expectancy_lb,
        profit_factor=profit_factor,
        max_drawdown=round(max_dd, 2),
        concentration=concentration,
    )


def compute_stats(trades: Iterable[ClosedTrade]) -> list[ModeStats]:
    """Per-(cohort, root, mode) stats: cohorts ascending, then root, then display order.

    Keying on the instrument *root* (not the dated symbol) keeps a quarterly roll from
    splitting a cohort, and keeps /MES and /MNQ evidence in separate buckets so one
    instrument's record can't buy the other's promotion."""
    groups: dict[tuple[str, str, str], list[ClosedTrade]] = defaultdict(list)
    for t in trades:
        groups[(resolve_cohort(t.session, t.version), resolve_root(t.symbol), t.mode)].append(t)

    def mode_rank(mode: str) -> int:
        return _MODE_ORDER.index(mode) if mode in _MODE_ORDER else len(_MODE_ORDER)

    stats = [_stats_for(cohort, root, mode, ts) for (cohort, root, mode), ts in groups.items()]
    stats.sort(key=lambda s: (s.cohort, s.root, mode_rank(s.mode)))
    return stats


# ── gate ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Gate:
    """Go-live promotion thresholds. A mode passes only on its CURRENT-cohort sample."""

    min_trades: int = 50
    min_sessions: int = 10
    min_profit_factor: float = 1.5
    max_concentration: float = 0.40

    def evaluate(self, s: ModeStats) -> list[str]:
        """Failure reasons; empty list == PASS."""
        reasons: list[str] = []
        if s.n < self.min_trades:
            reasons.append(f"n={s.n} < {self.min_trades}")
        if s.sessions < self.min_sessions:
            reasons.append(f"sessions={s.sessions} < {self.min_sessions}")
        if s.profit_factor < self.min_profit_factor:
            pf = "∞" if math.isinf(s.profit_factor) else f"{s.profit_factor:.2f}"
            reasons.append(f"PF {pf} < {self.min_profit_factor}")
        if s.expectancy_lb is None:
            reasons.append("expectancy CI needs n≥2")
        elif s.expectancy_lb <= 0:
            reasons.append(f"expectancy LB {s.expectancy_lb:+.2f} ≤ 0")
        if s.concentration is None:
            reasons.append("no winning sessions")
        elif s.concentration >= self.max_concentration:
            reasons.append(f"concentration {s.concentration:.0%} ≥ {self.max_concentration:.0%}")
        return reasons


# ── rendering ───────────────────────────────────────────────────────────────


def _fmt_pf(pf: float) -> str:
    return "∞" if math.isinf(pf) else f"{pf:.2f}"


def _fmt_opt(x: float | None, spec: str = "+.2f") -> str:
    return "n/a" if x is None else format(x, spec)


def render_table(stats: list[ModeStats]) -> str:
    """Markdown table, one row per (cohort, root, mode)."""
    if not stats:
        return "(no closed paper trades on record)"
    rows = [
        {
            "cohort": s.cohort,
            "root": s.root,
            "mode": s.mode,
            "n": s.n,
            "sess": s.sessions,
            "win%": f"{s.win_rate:.0%}",
            "total$": f"{s.total:+.0f}",
            "exp$": f"{s.expectancy:+.2f}",
            "exp_lb$": _fmt_opt(s.expectancy_lb),
            "PF": _fmt_pf(s.profit_factor),
            "maxDD$": f"{s.max_drawdown:.0f}",
            "conc": "n/a" if s.concentration is None else f"{s.concentration:.0%}",
        }
        for s in stats
    ]
    cols = [
        "cohort",
        "root",
        "mode",
        "n",
        "sess",
        "win%",
        "total$",
        "exp$",
        "exp_lb$",
        "PF",
        "maxDD$",
        "conc",
    ]
    return list_table(rows, cols)


def render_gate(stats: list[ModeStats], gate: Gate, cohort: str) -> str:
    """Per-(root, mode) PASS / failure-reason block for the current cohort only.

    Each instrument root is gated independently — promotion (git-tag → live) is per
    (root, mode), so /MES clearing a mode never green-lights /MNQ and vice versa."""
    current = [s for s in stats if s.cohort == cohort]
    lines = [
        f"Go-live gate — current cohort {cohort} "
        f"(n≥{gate.min_trades}, ≥{gate.min_sessions} sessions, "
        f"PF≥{gate.min_profit_factor}, exp LB>0, conc<{gate.max_concentration:.0%}):"
    ]
    if not current:
        lines.append("  (no closed trades in the current cohort yet)")
        return "\n".join(lines)
    for s in current:
        reasons = gate.evaluate(s)
        verdict = "PASS ✅" if not reasons else "hold — " + "; ".join(reasons)
        lines.append(f"  {s.root:6s} {s.mode:9s} {verdict}")
    return "\n".join(lines)


def render_scorecard(trades: list[ClosedTrade], gate: Gate | None = None) -> str:
    """Full text scorecard: per-cohort/mode table, pooled floor, then the go-live gate."""
    gate = gate or Gate()
    stats = compute_stats(trades)
    pooled = ""
    if trades:
        overall = _stats_for(
            "ALL", "ALL", "pooled", sorted(trades, key=lambda t: (t.session, t.ts))
        )
        pooled = (
            f"\nPooled floor (all cohorts, not a promotion basis): "
            f"n={overall.n}, win {overall.win_rate:.0%}, total {overall.total:+.0f}, "
            f"exp {overall.expectancy:+.2f}, PF {_fmt_pf(overall.profit_factor)}, "
            f"maxDD {overall.max_drawdown:.0f}"
        )
    return "\n".join(
        [
            render_table(stats),
            pooled,
            "",
            render_gate(stats, gate, current_cohort()),
        ]
    )


def write_chart(trades: list[ClosedTrade], path: Path) -> None:
    """Per-mode cumulative P&L over the chronological trade sequence, with cohort markers.

    A slope kink at a cohort boundary is the improvement verdict — readable at small n
    where a daily win-rate bar is just noise. matplotlib is imported lazily so it's a
    hard dependency of ``--chart`` only, never of the daemon or the text scorecard.
    """
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ModuleNotFoundError:
        sys.exit("matplotlib is required for --chart. Install it: `uv sync` (it's a dev dep).")

    ordered = sorted(trades, key=lambda t: (t.session, t.ts))
    if not ordered:
        sys.exit("No closed trades to chart.")

    fig, ax = plt.subplots(figsize=(11, 6))
    by_series: dict[str, list[tuple[int, float]]] = defaultdict(list)  # "{root} {mode}" curve
    running: dict[str, float] = defaultdict(float)
    for i, t in enumerate(ordered):
        key = f"{resolve_root(t.symbol)} {t.mode}"
        running[key] += t.pnl
        by_series[key].append((i, running[key]))
    for key in sorted(by_series):
        xs, ys = zip(*by_series[key], strict=True)
        ax.plot(xs, ys, marker=".", label=key)

    prev = None
    for i, t in enumerate(ordered):
        cohort = resolve_cohort(t.session, t.version)
        if prev is not None and cohort != prev:
            ax.axvline(i - 0.5, color="0.5", ls="--", lw=1)
            ax.text(
                i - 0.5,
                ax.get_ylim()[1],
                f"{prev}→{cohort}",
                rotation=90,
                va="top",
                ha="right",
                fontsize=8,
                color="0.4",
            )
        prev = cohort

    ax.axhline(0, color="0.7", lw=0.8)
    ax.set_xlabel("closed-trade sequence (chronological)")
    ax.set_ylabel("cumulative paper P&L ($)")
    ax.set_title("Scalper paper track record by verdict mode (dashed = version cohort boundary)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


# ── CLI ─────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Grade the scalper's paper track record by version cohort × instrument × mode."
    )
    parser.add_argument(
        "--root", type=Path, default=PAPER_ROOT, help=f"paper log directory (default: {PAPER_ROOT})"
    )
    parser.add_argument(
        "--chart", type=Path, default=None, help="also write a cumulative-P&L PNG to this path"
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="re-parse every session, ignoring the extraction cache",
    )
    args = parser.parse_args(argv)

    trades = load_closed_trades(args.root, use_cache=not args.no_cache)
    print(render_scorecard(trades))
    if args.chart:
        write_chart(trades, args.chart)
        print(f"\nChart written to {args.chart}")


if __name__ == "__main__":
    main()
