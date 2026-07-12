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
date: 2026-07-12
symbol: /MES
regime: fragile-pin
lean: long-only
session_caps:
  max_trades: 4
  daily_stop_usd: 300
levels:
  - {price: 6190.00, side: support,    stop: 6185.00}
  - {price: 6230.00, side: resistance, stop: 6235.00}
default_stop_points: 5
notes: "GEX +ve low %ile — pin fragile"
"""


def _write(path: Path, lean: str = "long-only") -> None:
    path.write_text(_SAMPLE.replace("lean: long-only", f"lean: {lean}"))


def test_load_parses_full_plan(tmp_path: Path) -> None:
    p = tmp_path / "2026-07-12-MES.yaml"
    _write(p)
    plan = load_session_plan(p)

    assert plan.symbol == "/MES"
    assert plan.lean == "long-only"
    assert plan.regime == "fragile-pin"
    assert plan.default_stop_points == 5
    assert plan.max_trades == 4
    assert plan.daily_stop_usd == 300
    assert plan.levels == [
        Level(6190.00, "support", stop=6185.00),
        Level(6230.00, "resistance", stop=6235.00),
    ]


def test_lean_defaults_to_no_trade_when_absent(tmp_path: Path) -> None:
    p = tmp_path / "plan.yaml"
    p.write_text("date: 2026-07-12\nsymbol: /MES\nregime: pin\n")
    assert load_session_plan(p).lean == "no-trade"


def test_plan_store_hot_reloads_on_change(tmp_path: Path) -> None:
    p = tmp_path / "2026-07-12-MES.yaml"
    _write(p, lean="long-only")
    store = PlanStore(p, reload_interval=0.0)  # disable throttle: re-stat every call
    first = store.current()
    assert first is not None and first.lean == "long-only"

    _write(p, lean="no-trade")
    os.utime(p, (time.time() + 10, time.time() + 10))  # force a newer mtime
    second = store.current()
    assert second is not None and second.lean == "no-trade"


def test_plan_store_keeps_last_good_on_malformed_edit(tmp_path: Path) -> None:
    p = tmp_path / "2026-07-12-MES.yaml"
    _write(p, lean="long-only")
    errors: list[str] = []
    store = PlanStore(p, reload_interval=0.0, on_error=errors.append)
    assert store.current().lean == "long-only"  # type: ignore[union-attr]

    p.write_text("levels:\n  - {side: support}\n")  # missing price -> raises on load
    os.utime(p, (time.time() + 10, time.time() + 10))
    survived = store.current()

    assert survived is not None and survived.lean == "long-only"  # last-good kept, no crash
    assert errors and "plan reload failed" in errors[0]


def test_plan_store_throttles_reload_within_interval(tmp_path: Path) -> None:
    p = tmp_path / "2026-07-12-MES.yaml"
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
    p = default_plan_path("MES", "2026-07-12", root=Path("/tmp/scalp"))
    assert p == Path("/tmp/scalp/2026-07-12-MES.yaml")


_SAMPLE_TRADEABLE = """\
date: 2026-07-12
symbol: /MES
regime: breakout-trend
lean: both
contracts: 2
default_stop_points: 5
default_target_points: 8
levels:
  - {price: 6190.00, side: support,    direction: long,  stop: 6185.00, target: 6200.00}
  - {price: 6230.00, side: resistance, direction: short, stop: 6235.00, target: 6215.00}
"""


def test_load_parses_direction_and_point_brackets(tmp_path: Path) -> None:
    p = tmp_path / "plan.yaml"
    p.write_text(_SAMPLE_TRADEABLE)
    plan = load_session_plan(p)

    assert plan.contracts == 2
    assert plan.default_stop_points == 5
    assert plan.default_target_points == 8
    assert plan.levels[0].direction == "long"
    assert plan.levels[0].stop == 6185.00 and plan.levels[0].target == 6200.00
    assert plan.levels[1].direction == "short"
    assert plan.levels[1].target == 6215.00


def test_direction_and_bracket_default_when_absent(tmp_path: Path) -> None:
    p = tmp_path / "2026-07-12-MES.yaml"
    _write(p)  # the original sample names no direction / target / default_target_points
    plan = load_session_plan(p)

    assert all(lvl.direction is None for lvl in plan.levels)  # alert-only
    assert all(lvl.target is None for lvl in plan.levels)
    assert plan.default_target_points == 8.0  # default when absent
    assert plan.contracts == 1


def test_level_stop_optional(tmp_path: Path) -> None:
    p = tmp_path / "plan.yaml"
    p.write_text(
        "date: 2026-07-12\nsymbol: /MES\nregime: pin\nlean: both\n"
        "levels:\n  - {price: 6190.00, side: support, direction: long}\n"
    )
    lvl = load_session_plan(p).levels[0]
    assert lvl.stop is None and lvl.target is None  # both derive from default points


def test_load_parses_zero_gamma_flip(tmp_path: Path) -> None:
    p = tmp_path / "plan.yaml"
    p.write_text(
        "date: 2026-07-12\nsymbol: /MES\nregime: fragile-pin\nlean: both\nzero_gamma: 6195.0\n"
    )
    assert load_session_plan(p).zero_gamma == 6195.0


def test_zero_gamma_defaults_to_none_when_absent(tmp_path: Path) -> None:
    p = tmp_path / "2026-07-12-MES.yaml"
    _write(p)  # the original sample names no zero_gamma
    assert load_session_plan(p).zero_gamma is None


def test_load_parses_level_mode_and_defaults_to_fade(tmp_path: Path) -> None:
    p = tmp_path / "plan.yaml"
    p.write_text(
        "date: 2026-07-12\nsymbol: /MES\nregime: breakout-trend\nlean: both\n"
        "levels:\n"
        "  - {price: 6230.00, side: resistance, mode: break, direction: long, stop: 6224.00}\n"
        "  - {price: 6190.00, side: support, stop: 6185.00}\n"
    )
    plan = load_session_plan(p)

    assert plan.levels[0].mode == "break"
    assert plan.levels[1].mode == "fade"  # default when absent
