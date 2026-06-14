"""Session-plan loading + hot-reload + graceful degrade.

The plan is the seam between `/scalp prep` and the daemon: a dated YAML the
detector and (later) the runtime read. These pin the parse, the mtime reload,
and the missing-file = None contract the whole graceful-degrade story rests on.
"""

import os
import time
from pathlib import Path

from trading_scalper.plan import Level, PlanStore, default_plan_path, load_session_plan

_SAMPLE = """\
date: 2026-06-12
symbol: QQQ
regime: fragile-pin
lean: long-only
session_caps:
  max_trades: 4
  daily_stop_usd: 300
levels:
  - {price: 719.40, side: support,    stop: 718.90}
  - {price: 723.10, side: resistance, stop: 723.70}
default_stop_pct: 0.15
notes: "GEX +ve low %ile — pin fragile"
"""


def _write(path: Path, lean: str = "long-only") -> None:
    path.write_text(_SAMPLE.replace("lean: long-only", f"lean: {lean}"))


def test_load_parses_full_plan(tmp_path: Path) -> None:
    p = tmp_path / "2026-06-12-QQQ.yaml"
    _write(p)
    plan = load_session_plan(p)

    assert plan.symbol == "QQQ"
    assert plan.lean == "long-only"
    assert plan.regime == "fragile-pin"
    assert plan.default_stop_pct == 0.15
    assert plan.max_trades == 4
    assert plan.daily_stop_usd == 300
    assert plan.levels == [
        Level(719.40, "support", 718.90),
        Level(723.10, "resistance", 723.70),
    ]


def test_lean_defaults_to_no_trade_when_absent(tmp_path: Path) -> None:
    p = tmp_path / "plan.yaml"
    p.write_text("date: 2026-06-12\nsymbol: QQQ\nregime: pin\n")
    assert load_session_plan(p).lean == "no-trade"


def test_plan_store_hot_reloads_on_change(tmp_path: Path) -> None:
    p = tmp_path / "2026-06-12-QQQ.yaml"
    _write(p, lean="long-only")
    store = PlanStore(p, reload_interval=0.0)  # disable throttle: re-stat every call
    first = store.current()
    assert first is not None and first.lean == "long-only"

    _write(p, lean="no-trade")
    os.utime(p, (time.time() + 10, time.time() + 10))  # force a newer mtime
    second = store.current()
    assert second is not None and second.lean == "no-trade"


def test_plan_store_keeps_last_good_on_malformed_edit(tmp_path: Path) -> None:
    p = tmp_path / "2026-06-12-QQQ.yaml"
    _write(p, lean="long-only")
    errors: list[str] = []
    store = PlanStore(p, reload_interval=0.0, on_error=errors.append)
    assert store.current().lean == "long-only"  # type: ignore[union-attr]

    p.write_text("levels:\n  - {side: support}\n")  # missing price/stop -> raises on load
    os.utime(p, (time.time() + 10, time.time() + 10))
    survived = store.current()

    assert survived is not None and survived.lean == "long-only"  # last-good kept, no crash
    assert errors and "plan reload failed" in errors[0]


def test_plan_store_throttles_reload_within_interval(tmp_path: Path) -> None:
    p = tmp_path / "2026-06-12-QQQ.yaml"
    _write(p, lean="long-only")
    now = [0.0]
    store = PlanStore(p, reload_interval=2.0, clock=lambda: now[0])
    assert store.current().lean == "long-only"  # type: ignore[union-attr]

    _write(p, lean="no-trade")
    os.utime(p, (time.time() + 10, time.time() + 10))
    now[0] = 1.0  # inside the 2s window -> the edit is NOT picked up yet
    assert store.current().lean == "long-only"  # type: ignore[union-attr]
    now[0] = 5.0  # past the window -> re-stat picks up the edit
    assert store.current().lean == "no-trade"  # type: ignore[union-attr]


def test_plan_store_missing_file_degrades_to_none(tmp_path: Path) -> None:
    store = PlanStore(tmp_path / "absent.yaml", reload_interval=0.0)
    assert store.current() is None


def test_default_plan_path() -> None:
    p = default_plan_path("QQQ", "2026-06-12", root=Path("/tmp/scalp"))
    assert p == Path("/tmp/scalp/2026-06-12-QQQ.yaml")


_SAMPLE_WITH_CONTRACTS = """\
date: 2026-06-12
symbol: QQQ
regime: breakout-trend
lean: both
contracts: 2
default_stop_pct: 0.20
target_pct: 0.25
levels:
  - {price: 719.40, side: support,    stop: 718.90, contract: "QQQ260612C00720000"}
  - {price: 723.10, side: resistance, stop: 723.70, contract: "QQQ260612P00723000"}
"""


def test_load_parses_contract_and_bracket_pcts(tmp_path: Path) -> None:
    p = tmp_path / "plan.yaml"
    p.write_text(_SAMPLE_WITH_CONTRACTS)
    plan = load_session_plan(p)

    assert plan.contracts == 2
    assert plan.default_stop_pct == 0.20
    assert plan.target_pct == 0.25
    assert plan.levels[0].contract == "QQQ260612C00720000"
    assert plan.levels[1].contract == "QQQ260612P00723000"


def test_contract_and_bracket_default_when_absent(tmp_path: Path) -> None:
    p = tmp_path / "2026-06-12-QQQ.yaml"
    _write(p)  # the original sample names no contract / target_pct / contracts
    plan = load_session_plan(p)

    assert all(lvl.contract is None for lvl in plan.levels)
    assert plan.target_pct == 0.20  # default when absent
    assert plan.contracts == 1


def test_load_parses_zero_gamma_flip(tmp_path: Path) -> None:
    p = tmp_path / "plan.yaml"
    p.write_text(
        "date: 2026-06-12\nsymbol: QQQ\nregime: fragile-pin\nlean: both\nzero_gamma: 719.95\n"
    )
    assert load_session_plan(p).zero_gamma == 719.95


def test_zero_gamma_defaults_to_none_when_absent(tmp_path: Path) -> None:
    p = tmp_path / "2026-06-12-QQQ.yaml"
    _write(p)  # the original sample names no zero_gamma
    assert load_session_plan(p).zero_gamma is None


def test_load_parses_level_mode_and_defaults_to_fade(tmp_path: Path) -> None:
    p = tmp_path / "plan.yaml"
    p.write_text(
        "date: 2026-06-12\nsymbol: QQQ\nregime: breakout-trend\nlean: both\n"
        "levels:\n"
        '  - {price: 723.10, side: resistance, stop: 723.70, mode: break, contract: "X"}\n'
        "  - {price: 719.40, side: support, stop: 718.90}\n"
    )
    plan = load_session_plan(p)

    assert plan.levels[0].mode == "break"
    assert plan.levels[1].mode == "fade"  # default when absent
