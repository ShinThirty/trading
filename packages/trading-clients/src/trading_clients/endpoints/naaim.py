"""NAAIM Exposure Index history — response model with z-score / percentile.

The NAAIM (National Association of Active Investment Managers) Exposure Index
is a weekly survey of active manager equity exposure, range -200 (max short,
leveraged) to +200 (max long, leveraged). Typical readings are 0-100.

Source: a single XLSX (since-inception) republished weekly at
www.naaim.org/wp-content/uploads/<year>/<month>/USE_Data-since-Inception_<date>.xlsx.
The discovery + download is handled in NaaimClient — this file just defines
the response model parsed from the XLSX bytes.

Headline number is the cross-sectional **mean** ("Mean/Average" column) of
manager responses for the week. We compute a 52-week z-score and percentile
on this series so positioning extremes (crowded long / max defensive) are
easy to surface — the same shape as the CFTC COT response.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from datetime import date, datetime
from statistics import mean, pstdev

import openpyxl

# Workbook columns — index of the headline series. Column A is the date.
# Layout (verified 2026-05): Date | Mean/Average | Most Bearish Response |
#   Quart 1 (25% at/below) | Quart 2 (median) | Quart 3 (25% at/above) |
#   Most Bullish Response | Standard Deviation | NAAIM Number | S&P 500
COL_DATE = 0
COL_MEAN = 1
COL_NAAIM = 8  # duplicate of mean — used as a sanity fallback
COL_SPX = 9


@dataclass
class NaaimHistoryEntry:
    week_ending: date
    exposure: float
    spx_close: float | None = None


@dataclass
class NaaimHistoryResponse:
    """Weekly NAAIM exposure history, newest-first.

    `entries` is the parsed time series. `latest_date` and `latest_exposure`
    surface the most recent reading; `z_score` and `percentile` are computed
    over the trailing 52 weeks (or whatever's available, minimum 8).
    """

    entries: list[NaaimHistoryEntry] = field(default_factory=list)

    @classmethod
    def from_response(cls, data: bytes) -> NaaimHistoryResponse:
        wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
        ws = wb.active
        if ws is None:
            return cls()

        entries: list[NaaimHistoryEntry] = []
        for row in ws.iter_rows(min_row=2, values_only=True):
            if not row or row[COL_DATE] is None:
                continue
            raw_date = row[COL_DATE]
            if isinstance(raw_date, datetime):
                d = raw_date.date()
            elif isinstance(raw_date, date):
                d = raw_date
            else:
                continue

            # Prefer the "Mean/Average" column; fall back to "NAAIM Number" if
            # missing (the two are duplicates in current sheets).
            raw = row[COL_MEAN] if len(row) > COL_MEAN else None
            if raw is None and len(row) > COL_NAAIM:
                raw = row[COL_NAAIM]
            try:
                exposure = float(raw) if raw is not None else None
            except (TypeError, ValueError):
                exposure = None
            if exposure is None:
                continue

            spx: float | None = None
            if len(row) > COL_SPX and row[COL_SPX] is not None:
                try:
                    spx = float(row[COL_SPX])
                except (TypeError, ValueError):
                    spx = None

            entries.append(NaaimHistoryEntry(week_ending=d, exposure=exposure, spx_close=spx))

        wb.close()

        # NAAIM ships the sheet newest-first but with occasional out-of-order
        # rows at the tail (verified 2026-05). Sort defensively.
        entries.sort(key=lambda e: e.week_ending, reverse=True)
        # Drop duplicate week-ending rows if any (keep first/newest).
        seen: set[date] = set()
        deduped: list[NaaimHistoryEntry] = []
        for e in entries:
            if e.week_ending in seen:
                continue
            seen.add(e.week_ending)
            deduped.append(e)
        return cls(entries=deduped)

    @property
    def latest(self) -> NaaimHistoryEntry | None:
        return self.entries[0] if self.entries else None

    @property
    def latest_exposure(self) -> float | None:
        return self.entries[0].exposure if self.entries else None

    @property
    def latest_date(self) -> str:
        return self.entries[0].week_ending.isoformat() if self.entries else ""

    @property
    def prior_exposure(self) -> float | None:
        return self.entries[1].exposure if len(self.entries) > 1 else None

    @property
    def wow_change(self) -> float | None:
        if self.latest_exposure is None or self.prior_exposure is None:
            return None
        return self.latest_exposure - self.prior_exposure

    def _window(self, weeks: int = 53) -> list[float]:
        return [e.exposure for e in self.entries[: min(len(self.entries), weeks)]]

    @property
    def z_score(self) -> float | None:
        """52-week z-score on exposure (latest vs trailing window)."""
        sample = self._window()
        if len(sample) < 8:
            return None
        mu = mean(sample)
        sd = pstdev(sample)
        if sd == 0:
            return None
        return (sample[0] - mu) / sd

    @property
    def percentile(self) -> float | None:
        """Where the latest exposure sits in the trailing 52w window (0=lowest, 100=highest)."""
        sample = self._window()
        if len(sample) < 8:
            return None
        latest = sample[0]
        below = sum(1 for v in sample[1:] if v < latest)
        return below / (len(sample) - 1) * 100

    @property
    def trailing_mean(self) -> float | None:
        sample = self._window()
        if len(sample) < 8:
            return None
        return mean(sample)

    def to_output(self) -> str:
        if not self.entries:
            return "(no NAAIM data)"
        lines = [f"Latest week ending: {self.latest_date}"]
        if self.latest_exposure is not None:
            lines.append(f"Exposure: {self.latest_exposure:.1f}")
        if self.wow_change is not None:
            lines.append(f"Week-over-week Δ: {self.wow_change:+.1f}")
        if self.trailing_mean is not None:
            lines.append(f"52w mean: {self.trailing_mean:.1f}")
        if self.z_score is not None:
            lines.append(f"52w z-score: {self.z_score:+.2f}")
        if self.percentile is not None:
            lines.append(f"52w percentile: {self.percentile:.0f}%")
        return "\n".join(lines)
