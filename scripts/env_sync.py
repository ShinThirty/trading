#!/usr/bin/env python3
"""Sync the trading environment between machines via an encrypted S3 bundle.

State bundled:
  - ~/.tradingrc                                   (API credentials, Webull token)
  - ~/.trading/                                    (SQLite DB: pipeline, rolls, decisions, TWSE cache)
  - ~/.claude/projects/.../memory/                 (Claude auto-memory)

Transport: S3.   Encryption: age (passphrase).   Snapshot: sqlite3 backup API.

Usage:
  uv run scripts/env_sync.py push     Bundle local state, encrypt, upload to S3
  uv run scripts/env_sync.py pull     Download from S3, decrypt, restore
  uv run scripts/env_sync.py status   Show local vs remote sync state

One-time setup:
  pacman -S age           # Linux: pacman / apt / dnf
                          # macOS:    brew install age
                          # Windows:  scoop install age   (or winget install FiloSottile.age)
  (S3 bucket is hardcoded in S3_URI below — edit if migrating accounts)

Workflow:
  Before leaving the desktop:  uv run scripts/env_sync.py push
  On the laptop (first time):  clone repo, install age + aws + uv, then pull
  On the laptop (each visit):  stop MCP server, then pull
  Before leaving the laptop:   uv run scripts/env_sync.py push
  Back at the desktop:         stop MCP server, then pull

Safety:
  - push refuses (unless --force) if the remote was updated by another host
    since your last sync, preventing accidental overwrite of the other machine
  - pull refuses (unless --force) if local files are newer than your last sync,
    preventing accidental overwrite of unpushed local work
  - the sqlite snapshot uses Python's built-in online backup API, safe to run
    while the MCP server is writing to the live DB
  - pull deletes leftover trading.db-wal / trading.db-shm before extracting
    so the restored DB starts clean
"""

from __future__ import annotations

import argparse
import json
import shutil
import socket
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import time
from contextlib import closing
from pathlib import Path

HOME = Path.home()
TRADINGRC = HOME / ".tradingrc"
TRADING_DIR = HOME / ".trading"
TRADING_DB = TRADING_DIR / "trading.db"
SYNC_MARKER = TRADING_DIR / ".last_sync"

# Claude Code stores per-project memory under ~/.claude/projects/<slug>/memory,
# where <slug> is the repo's absolute path with path separators and the Windows
# drive-letter colon all mapped to `-`. Derive from this script's location so it
# works on any machine regardless of where the repo lives.
#   /home/me/trading            → -home-me-trading
#   D:\Workspaces\me\trading    → D--Workspaces-me-trading
REPO_DIR = Path(__file__).resolve().parent.parent
_repo_slug = str(REPO_DIR).replace("\\", "-").replace("/", "-").replace(":", "-")
MEMORY_DIR = HOME / ".claude" / "projects" / _repo_slug / "memory"

S3_URI = "s3://trading-env-113477077840"
BUNDLE_NAME = "trading-env.tar.gz.age"
META_NAME = "trading-env.meta.json"


def require(*tools: str) -> None:
    missing = [t for t in tools if not shutil.which(t)]
    if missing:
        sys.exit(f"Missing tool(s): {', '.join(missing)}")


def tracked_files() -> list[Path]:
    """Files whose mtime determines whether local state has unsynced changes."""
    files: list[Path] = []
    if TRADINGRC.exists():
        files.append(TRADINGRC)
    if TRADING_DIR.exists():
        for p in TRADING_DIR.rglob("*"):
            if p.is_file() and p.name not in {".last_sync"} and not p.name.endswith(("-wal", "-shm")):
                files.append(p)
    if MEMORY_DIR.exists():
        files.extend(p for p in MEMORY_DIR.rglob("*") if p.is_file())
    return files


def latest_local_mtime() -> int:
    return int(max((f.stat().st_mtime for f in tracked_files()), default=0))


def read_marker() -> tuple[int, str]:
    if not SYNC_MARKER.exists():
        return 0, "(none)"
    raw = SYNC_MARKER.read_text().strip()
    if "|" not in raw:
        return 0, "(none)"
    ts, host = raw.split("|", 1)
    return int(ts), host


def write_marker(ts: int, host: str) -> None:
    TRADING_DIR.mkdir(parents=True, exist_ok=True)
    SYNC_MARKER.write_text(f"{ts}|{host}")


def fetch_remote_meta() -> dict | None:
    res = subprocess.run(
        ["aws", "s3", "cp", f"{S3_URI}/{META_NAME}", "-"],
        capture_output=True,
        text=True,
    )
    if res.returncode != 0:
        return None
    try:
        return json.loads(res.stdout)
    except json.JSONDecodeError:
        return None


def ts_to_str(ts: int) -> str:
    if not ts:
        return "never"
    return time.strftime("%Y-%m-%d %H:%M:%S %Z", time.localtime(ts))


def confirm(prompt: str) -> bool:
    return input(f"{prompt} [y/N] ").strip().lower() == "y"


def snapshot_sqlite(dst: Path) -> None:
    """Take an online-safe snapshot of trading.db using sqlite3's backup API."""
    if not TRADING_DB.exists():
        return
    with closing(sqlite3.connect(TRADING_DB)) as src, closing(sqlite3.connect(dst)) as bak:
        src.backup(bak)


def cmd_push(args: argparse.Namespace) -> None:
    require("age", "aws")

    remote = fetch_remote_meta()
    local_sync_ts, _ = read_marker()
    if remote and remote["push_ts"] > local_sync_ts and not args.force:
        print(
            f"WARNING: Remote was updated by {remote['hostname']} at "
            f"{ts_to_str(remote['push_ts'])} — after your last sync ({ts_to_str(local_sync_ts)})."
        )
        print("Pushing now will overwrite their changes.")
        if not confirm("Continue?"):
            sys.exit(1)

    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        staging = tmp / "stage"
        staging.mkdir()

        # Stage .tradingrc as-is.
        if TRADINGRC.exists():
            shutil.copy2(TRADINGRC, staging / ".tradingrc")

        # Stage .trading/ with a snapshot DB instead of the live file.
        if TRADING_DIR.exists():
            staged_trading = staging / ".trading"
            staged_trading.mkdir()
            for p in TRADING_DIR.iterdir():
                if p.name in {"trading.db", "trading.db-wal", "trading.db-shm", ".last_sync"}:
                    continue
                if p.is_file():
                    shutil.copy2(p, staged_trading / p.name)
                elif p.is_dir():
                    shutil.copytree(p, staged_trading / p.name)
            if TRADING_DB.exists():
                print("Snapshotting trading.db (safe while MCP server is running)...")
                snapshot_sqlite(staged_trading / "trading.db")

        # Stage memory dir under a fixed arcname (the source-machine slug
        # would not match the target machine's repo path).
        if MEMORY_DIR.exists():
            shutil.copytree(MEMORY_DIR, staging / "memory")

        tarball = tmp / "bundle.tar.gz"
        print("Bundling state...")
        with tarfile.open(tarball, "w:gz") as tar:
            for entry in staging.iterdir():
                tar.add(entry, arcname=entry.name)

        encrypted = tmp / BUNDLE_NAME
        print("Encrypting (you'll be prompted for the passphrase)...")
        subprocess.run(["age", "-p", "-o", str(encrypted), str(tarball)], check=True)

        push_ts = int(time.time())
        host = socket.gethostname()
        meta = {
            "push_ts": push_ts,
            "hostname": host,
            "date": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "bundle_bytes": encrypted.stat().st_size,
        }
        meta_path = tmp / META_NAME
        meta_path.write_text(json.dumps(meta))

        print(f"Uploading to {S3_URI}/ ({encrypted.stat().st_size / 1024:.1f} KiB)...")
        subprocess.run(
            ["aws", "s3", "cp", str(encrypted), f"{S3_URI}/{BUNDLE_NAME}"], check=True
        )
        subprocess.run(
            ["aws", "s3", "cp", str(meta_path), f"{S3_URI}/{META_NAME}"], check=True
        )

        write_marker(push_ts, host)
        print(f"Pushed. Marker updated: {ts_to_str(push_ts)} ({host})")


def cmd_pull(args: argparse.Namespace) -> None:
    require("age", "aws")

    remote = fetch_remote_meta()
    if not remote:
        sys.exit(f"No remote bundle found at {S3_URI}/")

    local_sync_ts, _ = read_marker()
    local_mtime = latest_local_mtime()

    if local_mtime > local_sync_ts and not args.force:
        print("WARNING: Local state has changes newer than your last sync.")
        print(f"  Last sync:           {ts_to_str(local_sync_ts)}")
        print(f"  Latest local change: {ts_to_str(local_mtime)}")
        print("Pulling will OVERWRITE these local changes.")
        if not confirm("Continue?"):
            sys.exit(1)

    if remote["push_ts"] == local_sync_ts and not args.force:
        print(f"Already in sync with remote (push_ts={remote['push_ts']}).")
        return

    # Refuse if the MCP server appears to be holding the DB open.
    wal = TRADING_DIR / "trading.db-wal"
    if wal.exists() and wal.stat().st_size > 0 and not args.force:
        print(
            "WARNING: trading.db-wal is non-empty — the MCP server may still be running."
        )
        print("Stop the MCP server first, or pass --force to proceed (may corrupt the DB).")
        if not confirm("Continue?"):
            sys.exit(1)

    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        encrypted = tmp / BUNDLE_NAME
        tarball = tmp / "bundle.tar.gz"

        print(f"Downloading from {S3_URI}/...")
        subprocess.run(
            ["aws", "s3", "cp", f"{S3_URI}/{BUNDLE_NAME}", str(encrypted)], check=True
        )

        print("Decrypting (you'll be prompted for the passphrase)...")
        subprocess.run(["age", "-d", "-o", str(tarball), str(encrypted)], check=True)

        # Remove stale WAL/SHM so the restored DB starts clean.
        for stale in (TRADING_DIR / "trading.db-wal", TRADING_DIR / "trading.db-shm"):
            stale.unlink(missing_ok=True)

        # Extract to a staging area, then route paths to their machine-specific
        # destinations. The bundle's `memory/` lands at this machine's MEMORY_DIR,
        # which is derived from where the repo lives here (not on the source).
        print("Extracting...")
        extract_dir = tmp / "extract"
        extract_dir.mkdir()
        with tarfile.open(tarball, "r:gz") as tar:
            tar.extractall(extract_dir, filter="data")

        src_rc = extract_dir / ".tradingrc"
        if src_rc.exists():
            shutil.copy2(src_rc, TRADINGRC)

        src_trading = extract_dir / ".trading"
        if src_trading.exists():
            TRADING_DIR.mkdir(parents=True, exist_ok=True)
            for entry in src_trading.iterdir():
                dst = TRADING_DIR / entry.name
                if dst.is_dir():
                    shutil.rmtree(dst)
                elif dst.exists():
                    dst.unlink()
                if entry.is_dir():
                    shutil.copytree(entry, dst)
                else:
                    shutil.copy2(entry, dst)

        src_mem = extract_dir / "memory"
        if src_mem.exists():
            if MEMORY_DIR.exists():
                shutil.rmtree(MEMORY_DIR)
            MEMORY_DIR.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src_mem, MEMORY_DIR)

        write_marker(remote["push_ts"], remote["hostname"])
        print(f"Pulled from {remote['hostname']} @ {ts_to_str(remote['push_ts'])}.")


def cmd_status(_: argparse.Namespace) -> None:
    remote = fetch_remote_meta()
    local_sync_ts, local_sync_host = read_marker()
    local_mtime = latest_local_mtime()

    print(f"Local ({socket.gethostname()}):")
    print(f"  Last sync:           {ts_to_str(local_sync_ts)} (from {local_sync_host})")
    print(f"  Latest local change: {ts_to_str(local_mtime)}")
    print()
    print(f"Remote ({S3_URI}):")
    if not remote:
        print("  No bundle uploaded yet")
        return
    print(f"  Last push: {ts_to_str(remote['push_ts'])} from {remote['hostname']}")
    if remote["push_ts"] == local_sync_ts:
        if local_mtime > local_sync_ts:
            print("  Status: marker in sync, but you have local changes — push to share")
        else:
            print("  Status: in sync")
    elif remote["push_ts"] > local_sync_ts:
        print("  Status: remote ahead — pull to update")
    else:
        print("  Status: local marker ahead of remote (unusual)")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    push = sub.add_parser("push", help="Bundle + encrypt + upload to S3")
    push.add_argument("--force", action="store_true", help="Skip remote-newer warning")
    push.set_defaults(func=cmd_push)

    pull = sub.add_parser("pull", help="Download + decrypt + extract")
    pull.add_argument("--force", action="store_true", help="Skip local-newer / WAL warnings")
    pull.set_defaults(func=cmd_pull)

    status = sub.add_parser("status", help="Show local vs remote sync state")
    status.set_defaults(func=cmd_status)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
