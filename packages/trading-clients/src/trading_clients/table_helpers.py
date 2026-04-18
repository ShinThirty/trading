"""Markdown table helper functions for API response rendering.

These helpers convert structured data into markdown tables for clean,
unambiguous LLM output. Used by response models in endpoints/*.py.
"""

from datetime import UTC, datetime
from typing import Any


def md_table(headers: list[str], rows: list[list[str]]) -> str:
    """Build a markdown table from headers and rows."""
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        cells = [str(c).replace("|", "\\|") for c in row]
        while len(cells) < len(headers):
            cells.append("")
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def kv_table(data: dict, key_header: str = "Field", val_header: str = "Value") -> str:
    """Build a two-column key/value markdown table from a dict."""
    headers = [key_header, val_header]
    rows = [[str(k), str(v)] for k, v in data.items() if v is not None]
    return md_table(headers, rows)


def list_table(items: list[dict], columns: list[str] | None = None) -> str:
    """Build a markdown table from a list of dicts.

    If columns is provided, only those keys are included (in that order).
    Otherwise all keys from the first item are used.
    """
    if not items:
        return "(no data)"
    if columns is None:
        seen: dict[str, None] = {}
        for item in items:
            seen.update(dict.fromkeys(item.keys()))
        columns = list(seen)
    rows = [[str(item.get(c, "")) for c in columns] for item in items]
    return md_table(columns, rows)


def to_float(val: Any) -> float | None:
    """Safely convert a value to float. Returns None if not possible."""
    if val is None or val == "":
        return None
    try:
        return float(str(val).replace(",", ""))
    except (ValueError, TypeError):
        return None


def to_float_zero(val: Any) -> float:
    """Safely convert a value to float. Returns 0.0 if not possible."""
    return to_float(val) or 0.0


def fmt_number(val: Any, decimals: int = 2) -> str:
    """Format a number with commas and fixed decimals, or return '' if None."""
    if val is None:
        return ""
    try:
        return f"{float(val):,.{decimals}f}"
    except (ValueError, TypeError):
        return str(val)


def fmt_large(val: Any) -> str:
    """Format large numbers as B/M/K for readability."""
    if val is None:
        return ""
    try:
        n = float(val)
    except (ValueError, TypeError):
        return str(val)
    if abs(n) >= 1e12:
        return f"{n / 1e12:.2f}T"
    if abs(n) >= 1e9:
        return f"{n / 1e9:.2f}B"
    if abs(n) >= 1e6:
        return f"{n / 1e6:.2f}M"
    if abs(n) >= 1e3:
        return f"{n / 1e3:.1f}K"
    return f"{n:.2f}"


def unix_to_date(ts: Any) -> str:
    """Convert unix timestamp to YYYY-MM-DD HH:MM."""
    if ts is None:
        return ""
    try:
        return datetime.fromtimestamp(int(ts), tz=UTC).strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError, OSError):
        return str(ts)
