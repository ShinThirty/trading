"""env_sync scalp retention — archive (gzip) past-window data instead of deleting it.

Pins the date/window helpers and the local archiver: files past their window get
gzipped in place and the original dropped; everything else is left untouched;
already-archived (.gz) and non-dated files are skipped; dry-run is a no-op.
"""

import gzip
import importlib.util
from datetime import date
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "env_sync", Path(__file__).resolve().parent.parent / "scripts" / "env_sync.py"
)
env_sync = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(env_sync)

TODAY = date(2026, 6, 29)


def test_scalp_file_date_parses_leading_iso_date() -> None:
    assert env_sync._scalp_file_date("2026-06-29-QQQ.yaml") == date(2026, 6, 29)
    assert env_sync._scalp_file_date("2026-05-01-tape.jsonl") == date(2026, 5, 1)
    assert env_sync._scalp_file_date("summary.json") is None
    assert env_sync._scalp_file_date("README.md") is None


def test_archive_after_days_is_short_for_tape_long_for_logs() -> None:
    tape, log = env_sync.TAPE_ARCHIVE_AFTER_DAYS, env_sync.LOG_ARCHIVE_AFTER_DAYS
    assert env_sync._archive_after_days("2026-05-01-tape.jsonl") == tape
    assert env_sync._archive_after_days("2026-05-01-signals.jsonl") == log
    assert env_sync._archive_after_days("2026-05-01.jsonl") == log


def test_scalp_archivable_windows_and_skips() -> None:
    # tape: 59 days old > 30 -> archivable; 9 days old -> not
    assert env_sync._scalp_archivable("2026-05-01-tape.jsonl", TODAY) is True
    assert env_sync._scalp_archivable("2026-06-20-tape.jsonl", TODAY) is False
    # logs: 59 days < 365 -> keep; 544 days > 365 -> archivable
    assert env_sync._scalp_archivable("2026-05-01-signals.jsonl", TODAY) is False
    assert env_sync._scalp_archivable("2025-01-01-summary.json", TODAY) is True
    # already archived, and non-dated, are never re-archived
    assert env_sync._scalp_archivable("2026-01-01-tape.jsonl.gz", TODAY) is False
    assert env_sync._scalp_archivable("README.md", TODAY) is False


def _tree(root: Path) -> None:
    paper = root / "paper"
    paper.mkdir(parents=True)
    (root / "2026-06-29-QQQ.yaml").write_text("plan: today\n")  # keep (today)
    (paper / "2026-06-20-tape.jsonl").write_text("recent tape\n")  # keep (< 30d)
    (paper / "2026-05-01-tape.jsonl").write_text('{"p":719.4}\n' * 50)  # archive (> 30d)
    (paper / "2026-05-01-signals.jsonl").write_text("sig\n")  # keep (log < 365d)
    (paper / "2025-01-01-summary.json").write_text('{"pnl":1}\n')  # archive (log > 365d)


def test_archive_local_gzips_past_window_and_drops_originals(tmp_path: Path) -> None:
    _tree(tmp_path)
    archived = env_sync.archive_scalp_local(TODAY, root=tmp_path)

    assert [p.name for p in archived] == ["2025-01-01-summary.json", "2026-05-01-tape.jsonl"]
    # originals replaced by .gz; content round-trips through gzip
    tape_gz = tmp_path / "paper" / "2026-05-01-tape.jsonl.gz"
    assert tape_gz.exists()
    assert not (tmp_path / "paper" / "2026-05-01-tape.jsonl").exists()
    assert gzip.open(tape_gz, "rt").read() == '{"p":719.4}\n' * 50
    # in-window + lightweight-recent files are untouched
    assert (tmp_path / "paper" / "2026-06-20-tape.jsonl").exists()
    assert (tmp_path / "paper" / "2026-05-01-signals.jsonl").exists()
    assert (tmp_path / "2026-06-29-QQQ.yaml").exists()


def test_archive_local_is_idempotent_keeps_existing_gz(tmp_path: Path) -> None:
    paper = tmp_path / "paper"
    paper.mkdir(parents=True)
    (paper / "2026-05-01-tape.jsonl").write_text("fresh\n")
    (paper / "2026-05-01-tape.jsonl.gz").write_bytes(gzip.compress(b"already archived\n"))

    env_sync.archive_scalp_local(TODAY, root=tmp_path)

    # the pre-existing archive is preserved (not re-compressed), the original dropped
    assert not (paper / "2026-05-01-tape.jsonl").exists()
    assert gzip.open(paper / "2026-05-01-tape.jsonl.gz", "rb").read() == b"already archived\n"


def test_archive_local_dry_run_changes_nothing(tmp_path: Path) -> None:
    _tree(tmp_path)
    archived = env_sync.archive_scalp_local(TODAY, root=tmp_path, dry_run=True)

    assert [p.name for p in archived] == ["2025-01-01-summary.json", "2026-05-01-tape.jsonl"]
    assert (tmp_path / "paper" / "2026-05-01-tape.jsonl").exists()  # still there
    assert not (tmp_path / "paper" / "2026-05-01-tape.jsonl.gz").exists()  # nothing written


def test_archive_local_no_dir_is_noop(tmp_path: Path) -> None:
    assert env_sync.archive_scalp_local(TODAY, root=tmp_path / "absent") == []
