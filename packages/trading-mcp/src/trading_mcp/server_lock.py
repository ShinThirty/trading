"""Best-effort PID lockfile so env_sync can detect a running MCP server.

The file lives next to the SQLite DB (~/.trading/mcp-server.lock) and holds this
process's pid + hostname + start time as JSON. It is deliberately NOT synced
(scripts/env_sync.py excludes it by name). Written on server startup, removed on
clean shutdown; a crash leaves it behind, but env_sync treats a lock whose pid is
no longer alive as stale and ignores/removes it.

A WAL checkpoint alone can't see an *idle* server (an idle connection holds no
lock), so this lockfile is the authoritative "server is running" signal.
"""

from __future__ import annotations

import json
import os
import socket
from datetime import UTC, datetime
from pathlib import Path

LOCK_PATH = Path.home() / ".trading" / "mcp-server.lock"


def acquire(path: Path = LOCK_PATH) -> None:
    """Record this process as the live MCP server (overwrites any stale lock)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "pid": os.getpid(),
        "hostname": socket.gethostname(),
        "started_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    path.write_text(json.dumps(payload))


def release(path: Path = LOCK_PATH) -> None:
    """Drop the lockfile on clean shutdown."""
    path.unlink(missing_ok=True)
