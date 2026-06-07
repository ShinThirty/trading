#!/usr/bin/env python3
"""Sync the trading environment between machines via an encrypted S3 bundle.

State bundled:
  - ~/.tradingrc                                   (API credentials, Webull token)
  - ~/.trading/                                    (SQLite DB: pipeline, rolls, decisions, cache)
  - ~/.claude/projects/.../memory/                 (Claude auto-memory)
  - ~/Documents/analysis/                          (per-ticker research notes)

Transport: S3.   Encryption: age (X25519 keypair).   Snapshot: sqlite3 backup API.

Usage:
  uv run scripts/env_sync.py push       Bundle local state, encrypt, upload to S3
  uv run scripts/env_sync.py pull       Download from S3, decrypt, restore
  uv run scripts/env_sync.py status     Show local vs remote sync state
  uv run scripts/env_sync.py setup-key  Create the shared age keypair (run once)

One-time setup:
  pacman -S age           # Linux: pacman / apt / dnf
                          # macOS:    brew install age
                          # Windows:  scoop install age   (or winget install FiloSottile.age)
  uv run scripts/env_sync.py setup-key   # generate the shared keypair (first machine)
  # Then copy the identity file (default ~/.config/age/trading-env.txt) to every
  # other machine that syncs — same path, or point TRADING_ENV_AGE_IDENTITY at it.
  # The keypair replaces the old passphrase: push/pull no longer prompt.
  (S3 bucket is hardcoded in BUCKET below — edit if migrating accounts.)

Bucket safety (set once, server-side):
  - Versioning enabled — overwrites and deletes keep prior versions.
  - Lifecycle expires noncurrent versions after 30 days (and aborts incomplete
    multipart uploads after 1 day).
  Both are pure insurance against bad pushes / accidental deletion.

Workflow:
  Before leaving the desktop:  stop MCP server, then push
  On the laptop (first time):  clone repo, install age + aws + uv, then pull
  On the laptop (each visit):  stop MCP server, then pull
  Before leaving the laptop:   stop MCP server, then push
  Back at the desktop:         stop MCP server, then pull

Safety:
  - Atomic publish: bundle data + meta (push_ts, hostname, content_hash, …)
    live in a single S3 object as the object's user metadata. A failed upload
    never leaves a torn state visible to readers.
  - Compare-and-swap: each push uses S3 If-Match against the object's ETag, so
    two machines pushing concurrently can't silently overwrite each other —
    the loser is told to pull first.
  - Running-server guard: the MCP server writes a PID lockfile
    (~/.trading/mcp-server.lock, never synced) on startup and removes it on clean
    exit. push/pull ABORT if that lock names a live process on this host; a lock
    whose process is gone (crash) is treated as stale and removed. This catches an
    idle server that a WAL checkpoint alone would miss.
  - WAL checkpoint before signing: push/pull fold trading.db's WAL into the main
    file (PRAGMA wal_checkpoint(TRUNCATE)) before computing the signature, so the
    size+mtime fingerprint can't miss committed-but-un-checkpointed writes. Both
    also abort if the DB is locked by some other writer. status warns instead of
    aborting on either condition — it is read-only.
  - Local dirty detection: the marker stores a manifest signature (sha256 of
    text-file contents + size/mtime of the checkpointed DB file). The signature,
    not raw mtime, drives the "you have local changes" warning on pull.
  - sqlite snapshot uses Python's built-in online backup API for a consistent
    capture of the (now checkpointed) DB.
  - pull deletes leftover trading.db-wal / trading.db-shm before extracting so
    the restored DB starts clean.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
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
# PID lockfile the MCP server writes on startup (trading_mcp/server_lock.py).
# Never synced — it names a process on one machine. Its presence + a live pid is
# the authoritative "server is running" signal.
MCP_LOCK_NAME = "mcp-server.lock"
MCP_LOCK = TRADING_DIR / MCP_LOCK_NAME

# Claude Code stores per-project memory under ~/.claude/projects/<slug>/memory,
# where <slug> is the repo's absolute path with path separators and the Windows
# drive-letter colon all mapped to `-`. Derive from this script's location so it
# works on any machine regardless of where the repo lives.
#   /home/me/trading            → -home-me-trading
#   D:\Workspaces\me\trading    → D--Workspaces-me-trading
REPO_DIR = Path(__file__).resolve().parent.parent
_repo_slug = str(REPO_DIR).replace("\\", "-").replace("/", "-").replace(":", "-")
MEMORY_DIR = HOME / ".claude" / "projects" / _repo_slug / "memory"

# Per-ticker research notes (plain markdown). Lives under HOME so it rides the
# same logical-rel signature path; restored to the same place on every machine.
DOCS_DIR = HOME / "Documents" / "analysis"

BUCKET = "trading-env-113477077840"
S3_URI = f"s3://{BUCKET}"
KEY_BUNDLE = "trading-env.tar.gz.age"

# age identity (X25519 keypair) used to encrypt/decrypt the bundle without a
# passphrase prompt. ONE keypair is shared across machines: create it once with
# `setup-key`, then copy the file to every machine that syncs (same path, or
# point TRADING_ENV_AGE_IDENTITY at it). The private key is never bundled or
# uploaded — only the matching public recipient encrypts the S3 object.
AGE_IDENTITY = Path(
    os.environ.get("TRADING_ENV_AGE_IDENTITY", str(HOME / ".config" / "age" / "trading-env.txt"))
)


def require(*tools: str) -> None:
    missing = [t for t in tools if not shutil.which(t)]
    if missing:
        sys.exit(f"Missing tool(s): {', '.join(missing)}")


def require_identity() -> None:
    if not AGE_IDENTITY.exists():
        sys.exit(
            f"No age identity at {AGE_IDENTITY}.\n"
            "Run `uv run scripts/env_sync.py setup-key` on one machine, then copy that\n"
            "identity file to this one (same path, or set TRADING_ENV_AGE_IDENTITY)."
        )


def age_recipient() -> str:
    """Public recipient (age1...) derived from the local identity file."""
    require_identity()
    res = subprocess.run(["age-keygen", "-y", str(AGE_IDENTITY)], capture_output=True, text=True)
    if res.returncode != 0:
        sys.exit(f"Could not read age identity {AGE_IDENTITY}:\n{res.stderr.strip()}")
    return res.stdout.strip()


def tracked_files() -> list[Path]:
    """Files that contribute to the local signature."""
    files: list[Path] = []
    if TRADINGRC.exists():
        files.append(TRADINGRC)
    if TRADING_DIR.exists():
        for p in TRADING_DIR.rglob("*"):
            if not p.is_file() or p.name in {".last_sync", MCP_LOCK_NAME}:
                continue
            if p.name.endswith(("-wal", "-shm")):
                continue
            files.append(p)
    if MEMORY_DIR.exists():
        files.extend(p for p in MEMORY_DIR.rglob("*") if p.is_file())
    if DOCS_DIR.exists():
        files.extend(p for p in DOCS_DIR.rglob("*") if p.is_file())
    return files


def latest_local_mtime() -> int:
    return int(max((f.stat().st_mtime for f in tracked_files()), default=0))


def _logical_rel(p: Path) -> str:
    return str(p.relative_to(HOME)).replace("\\", "/")


def _file_record(p: Path) -> str:
    """Manifest line for one tracked file.

    Text files (.tradingrc, memory/*) → sha256 of content. DB files
    (.trading/*) → size + int(mtime); hashing trading.db's bytes is expensive
    and unstable (sqlite page shuffling) while mtime/size already moves on any
    real write.
    """
    rel = _logical_rel(p)
    if p.is_relative_to(TRADING_DIR):
        st = p.stat()
        return f"{rel}|size:{st.st_size}|mtime:{int(st.st_mtime)}"
    with open(p, "rb") as f:
        digest = hashlib.file_digest(f, "sha256").hexdigest()
    return f"{rel}|sha256:{digest}"


def live_signature() -> str:
    """sha256 over a sorted manifest of tracked files (live, not staged)."""
    h = hashlib.sha256()
    for p in sorted(tracked_files(), key=_logical_rel):
        h.update(_file_record(p).encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def read_marker() -> tuple[int, str, str | None]:
    """Return (push_ts, hostname, signature). signature is None for legacy 2-field markers."""
    if not SYNC_MARKER.exists():
        return 0, "(none)", None
    raw = SYNC_MARKER.read_text().strip()
    if "|" not in raw:
        return 0, "(none)", None
    parts = raw.split("|")
    ts = int(parts[0]) if parts[0].isdigit() else 0
    host = parts[1] if len(parts) > 1 else "(none)"
    sig = parts[2] if len(parts) > 2 and parts[2] else None
    return ts, host, sig


def write_marker(ts: int, host: str, sig: str) -> None:
    TRADING_DIR.mkdir(parents=True, exist_ok=True)
    SYNC_MARKER.write_text(f"{ts}|{host}|{sig}")


def fetch_remote_meta() -> dict | None:
    """Return remote state from the bundle object's user metadata.

    Result keys: etag, push_ts, hostname, date, bundle_bytes, content_hash.
    Returns None when no remote bundle exists (S3 404).
    """
    res = subprocess.run(
        ["aws", "s3api", "head-object", "--bucket", BUCKET, "--key", KEY_BUNDLE],
        capture_output=True,
        text=True,
    )
    if res.returncode != 0:
        if "(404)" in res.stderr or "Not Found" in res.stderr:
            return None
        sys.exit(f"head-object failed:\n{res.stderr.strip()}")
    try:
        data = json.loads(res.stdout)
    except json.JSONDecodeError:
        return None
    etag = data.get("ETag")
    meta = data.get("Metadata") or {}
    return {
        "etag": etag,
        "push_ts": int(meta["push-ts"]),
        "hostname": meta.get("hostname", "(unknown)"),
        "date": meta.get("date", ""),
        "bundle_bytes": int(meta.get("bundle-bytes", 0)),
        "content_hash": meta.get("content-hash"),
    }


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


class DatabaseLockedError(Exception):
    """trading.db could not be checkpointed because another connection holds it."""


def checkpoint_db() -> None:
    """Fold trading.db's WAL into the main file so size+mtime see every committed write.

    The sync signature fingerprints trading.db by size+mtime (hashing its bytes
    is expensive and unstable). In WAL mode, committed writes can sit in the -wal
    file without moving the main file's size/mtime until a checkpoint, so change
    detection would silently miss them. Checkpointing here closes that gap.

    Raises DatabaseLockedError if the DB is locked, or a TRUNCATE checkpoint can't
    complete because another connection (typically a running MCP server) is using
    it — in which case the signature can't be trusted and the caller should stop.
    """
    if not TRADING_DB.exists():
        return
    try:
        with closing(sqlite3.connect(TRADING_DB, timeout=2.0)) as conn:
            busy, _log, _ckpt = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
    except sqlite3.OperationalError as e:
        raise DatabaseLockedError(f"trading.db is locked: {e}") from e
    if busy:
        raise DatabaseLockedError(
            "trading.db checkpoint was blocked — another connection holds the DB."
        )
    # A successful TRUNCATE checkpoint zeroes the WAL; if it has grown back, another
    # process is actively writing (the MCP server is still running).
    wal = TRADING_DIR / "trading.db-wal"
    if wal.exists() and wal.stat().st_size > 0:
        raise DatabaseLockedError(
            "trading.db-wal repopulated right after checkpoint — the DB is in use."
        )


def _pid_alive(pid: int) -> bool:
    """True if a process with this pid currently exists (cross-platform)."""
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        process_query = 0x1000  # PROCESS_QUERY_LIMITED_INFORMATION
        still_active = 259  # STILL_ACTIVE
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.OpenProcess(process_query, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return code.value == still_active
            return True
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, owned by another user
    return True


def running_mcp_server() -> dict | None:
    """Return the lockfile info if a live MCP server holds the DB on this host.

    Cleans up a stale lockfile (crashed server, or unreadable garbage) as a side
    effect. A lock whose hostname isn't this machine's is ignored without
    deletion (it should never be synced, but be defensive).
    """
    if not MCP_LOCK.exists():
        return None
    try:
        info = json.loads(MCP_LOCK.read_text())
        pid = int(info["pid"])
    except (OSError, ValueError, KeyError, TypeError):
        MCP_LOCK.unlink(missing_ok=True)
        return None
    if info.get("hostname") != socket.gethostname():
        return None
    if _pid_alive(pid):
        return info
    MCP_LOCK.unlink(missing_ok=True)
    return None


def ensure_db_checkpointed() -> None:
    """Checkpoint the DB before signing; abort the command if the DB is in use."""
    server = running_mcp_server()
    if server:
        sys.exit(
            f"MCP server is running (pid {server['pid']} on {server.get('hostname')}, "
            f"started {server.get('started_at', '?')}). Stop it before syncing.\n"
            f"Lockfile: {MCP_LOCK}"
        )
    try:
        checkpoint_db()
    except DatabaseLockedError as e:
        sys.exit(
            f"{e}\n"
            "Stop the MCP server (or whatever holds trading.db open) and retry — its "
            "WAL must be checkpointed before the sync signature is trustworthy."
        )


def _is_dirty(local_sync_ts: int, local_sig: str | None) -> bool:
    """True if local state differs from the last-sync baseline.

    Prefers signature comparison; falls back to mtime when the marker predates
    the signature field (first run after upgrade).
    """
    if local_sig is not None:
        return live_signature() != local_sig
    return latest_local_mtime() > local_sync_ts


def cmd_push(args: argparse.Namespace) -> None:
    require("age", "age-keygen", "aws")
    recipient = age_recipient()
    ensure_db_checkpointed()

    remote = fetch_remote_meta()
    local_sync_ts, _, _ = read_marker()
    if remote and remote["push_ts"] > local_sync_ts and not args.force:
        print(
            f"WARNING: Remote was updated by {remote['hostname']} at "
            f"{ts_to_str(remote['push_ts'])} — after your last sync ({ts_to_str(local_sync_ts)})."
        )
        print("Pushing now will overwrite their changes.")
        if not confirm("Continue?"):
            sys.exit(1)

    live_sig = live_signature()

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
                if p.name in {
                    "trading.db",
                    "trading.db-wal",
                    "trading.db-shm",
                    ".last_sync",
                    MCP_LOCK_NAME,
                }:
                    continue
                if p.is_file():
                    shutil.copy2(p, staged_trading / p.name)
                elif p.is_dir():
                    shutil.copytree(p, staged_trading / p.name)
            if TRADING_DB.exists():
                print("Snapshotting trading.db...")
                snapshot_sqlite(staged_trading / "trading.db")

        # Stage memory dir under a fixed arcname (the source-machine slug would
        # not match the target machine's repo path).
        if MEMORY_DIR.exists():
            shutil.copytree(MEMORY_DIR, staging / "memory")

        # Stage analysis docs under a fixed arcname (HOME path differs per machine).
        if DOCS_DIR.exists():
            shutil.copytree(DOCS_DIR, staging / "analysis")

        tarball = tmp / "bundle.tar.gz"
        print("Bundling state...")
        with tarfile.open(tarball, "w:gz") as tar:
            for entry in staging.iterdir():
                tar.add(entry, arcname=entry.name)

        encrypted = tmp / KEY_BUNDLE
        print("Encrypting...")
        subprocess.run(["age", "-r", recipient, "-o", str(encrypted), str(tarball)], check=True)

        push_ts = int(time.time())
        host = socket.gethostname()
        metadata = {
            "push-ts": str(push_ts),
            "hostname": host,
            "date": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "bundle-bytes": str(encrypted.stat().st_size),
            "content-hash": live_sig,
        }

        print(f"Uploading to {S3_URI}/ ({encrypted.stat().st_size / 1024:.1f} KiB)...")
        cmd = [
            "aws",
            "s3api",
            "put-object",
            "--bucket",
            BUCKET,
            "--key",
            KEY_BUNDLE,
            "--body",
            str(encrypted),
            "--metadata",
            json.dumps(metadata),
        ]
        if remote and remote.get("etag"):
            cmd.extend(["--if-match", remote["etag"]])
        else:
            cmd.extend(["--if-none-match", "*"])

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            if "PreconditionFailed" in result.stderr or "pre-conditions" in result.stderr.lower():
                sys.exit(
                    "Push aborted: remote was updated by another machine between "
                    "your check and your upload. Pull first, then retry."
                )
            sys.exit(f"Upload failed:\n{result.stderr.strip()}")

        write_marker(push_ts, host, live_sig)
        print(f"Pushed. Marker updated: {ts_to_str(push_ts)} ({host})")


def cmd_pull(args: argparse.Namespace) -> None:
    require("age", "aws")
    # Fold the WAL in (and refuse if the MCP server still holds the DB) so the
    # dirty check below can't miss un-checkpointed local writes and silently
    # overwrite them.
    ensure_db_checkpointed()

    remote = fetch_remote_meta()
    if not remote:
        sys.exit(f"No remote bundle found at {S3_URI}/")

    local_sync_ts, _, local_sig = read_marker()

    if _is_dirty(local_sync_ts, local_sig) and not args.force:
        print("WARNING: Local state has changes since your last sync.")
        print(f"  Last sync: {ts_to_str(local_sync_ts)}")
        print("Pulling will OVERWRITE these local changes.")
        if not confirm("Continue?"):
            sys.exit(1)

    if remote["push_ts"] == local_sync_ts and not args.force:
        print(f"Already in sync with remote (push_ts={remote['push_ts']}).")
        return

    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        encrypted = tmp / KEY_BUNDLE
        tarball = tmp / "bundle.tar.gz"

        print(f"Downloading from {S3_URI}/...")
        subprocess.run(["aws", "s3", "cp", f"{S3_URI}/{KEY_BUNDLE}", str(encrypted)], check=True)

        require_identity()
        print("Decrypting...")
        subprocess.run(
            ["age", "-d", "-i", str(AGE_IDENTITY), "-o", str(tarball), str(encrypted)],
            check=True,
        )

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

        src_docs = extract_dir / "analysis"
        if src_docs.exists():
            if DOCS_DIR.exists():
                shutil.rmtree(DOCS_DIR)
            DOCS_DIR.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src_docs, DOCS_DIR)

        post_sig = live_signature()
        write_marker(remote["push_ts"], remote["hostname"], post_sig)
        print(f"Pulled from {remote['hostname']} @ {ts_to_str(remote['push_ts'])}.")


def cmd_status(_: argparse.Namespace) -> None:
    # Read-only command: detect a running server / checkpoint best-effort so the
    # signature is accurate, but only flag (don't abort) if the DB is in use.
    server = running_mcp_server()
    db_locked = False
    if not server:
        try:
            checkpoint_db()
        except DatabaseLockedError:
            db_locked = True

    remote = fetch_remote_meta()
    local_sync_ts, local_sync_host, local_sig = read_marker()
    dirty = _is_dirty(local_sync_ts, local_sig)

    print(f"Local ({socket.gethostname()}):")
    print(f"  Last sync:    {ts_to_str(local_sync_ts)} (from {local_sync_host})")
    if local_sig is not None:
        print(f"  Local state:  {'changed since last sync' if dirty else 'matches last sync'}")
    else:
        suffix = " (dirty)" if dirty else ""
        print(f"  Latest mtime: {ts_to_str(latest_local_mtime())}{suffix}")
    if server:
        print(
            f"  DB:           MCP server RUNNING (pid {server['pid']}) — "
            "local state may be incomplete; stop it before syncing"
        )
    elif db_locked:
        print("  DB:           LOCKED — change detection may miss un-checkpointed writes")
    print()
    print(f"Remote ({S3_URI}):")
    if not remote:
        print("  No bundle uploaded yet")
        return
    print(f"  Last push: {ts_to_str(remote['push_ts'])} from {remote['hostname']}")
    if remote["push_ts"] == local_sync_ts:
        if dirty:
            print("  Status: marker in sync, but you have local changes — push to share")
        else:
            print("  Status: in sync")
    elif remote["push_ts"] > local_sync_ts:
        print("  Status: remote ahead — pull to update")
    else:
        print("  Status: local marker ahead of remote (unusual)")


def cmd_setup_key(_: argparse.Namespace) -> None:
    require("age-keygen")
    if AGE_IDENTITY.exists():
        print(f"Identity already exists: {AGE_IDENTITY}")
        print(f"Recipient (public key): {age_recipient()}")
        print("Copy this file to your other machines to let them decrypt the bundle.")
        return
    AGE_IDENTITY.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["age-keygen", "-o", str(AGE_IDENTITY)], check=True)
    try:
        AGE_IDENTITY.chmod(0o600)
    except OSError:
        pass
    print(f"\nCreated age identity: {AGE_IDENTITY}")
    print(f"Recipient (public key): {age_recipient()}")
    print(
        "\nNext steps:\n"
        f"  1. Copy {AGE_IDENTITY} to your other machines (same path, or set\n"
        "     TRADING_ENV_AGE_IDENTITY to wherever you keep it).\n"
        "  2. Run `push` here to re-encrypt the S3 bundle with the key.\n"
        "After that, push/pull never prompt for a passphrase."
    )


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

    setup = sub.add_parser("setup-key", help="Create the shared age keypair (run once)")
    setup.set_defaults(func=cmd_setup_key)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
