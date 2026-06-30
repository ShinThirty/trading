"""Shadow-mode volume observers: a session Volume Profile + a rolling volume rate.

SHADOW ONLY by intent. These are pure-computation observers fed the same underlying
tape the detector sees; **nothing in the decision path reads them**. The point is to
accumulate the data — over upcoming sessions — to decide *from evidence* whether the
break-side VAP read (an LVN void vs a thick HVN on the far side of a wall) predicts a
runner before it ever gates or sizes a trade (the open #1 "runaway-gap"). Same posture
as the B4 ``FireRecord`` telemetry: record, never act, prove first.

Two distinct signals, kept separate on purpose:

- :class:`VolumeProfile` — *locational* structure (where volume has transacted: POC,
  value area, high-/low-volume nodes). This is geometry, the same kind of input a
  gamma wall is, and the natural future *level source*.
- :class:`VolumeRate` — *temporal* confirmation (is a move on expanding or contracting
  volume). This is the explicitly **lower-priority** idea — a confidence/size modulator
  at most, never a fire gate (the B4 absorption gate died trying to veto geometry).

No I/O, no port, no broker — like ``BreakoutTracker`` and ``indicators.py``. The disk
side (raw-tape capture + periodic snapshots) lives in ``shadow.py``.
"""

from collections import deque
from dataclasses import dataclass, field


@dataclass(slots=True)
class VolumeProfile:
    """Session volume-at-price histogram in fixed ``bucket``-wide price bins.

    Fed every executed print via :meth:`add` (price, size); accumulates traded volume
    per bin. Derives the POC (the heaviest bin), the value area (the contiguous band
    around the POC holding ``value_area_pct`` of total volume → VAL/VAH), and an
    HVN/LVN classification per price (heavy vs thin vs normal, relative to the mean bin
    volume). All structure — no time, no tape rate.

    A bin is keyed by ``round(price / bucket)`` so $0.10 buckets land prices on a dime
    grid. The histogram is fully rebuildable offline from the captured raw tape, so the
    bucket/threshold choices here are cheap to revise later.
    """

    bucket: float = 0.10
    value_area_pct: float = 0.70
    hvn_mult: float = 1.5  # bin volume > hvn_mult * mean(bins) = a high-volume node
    lvn_mult: float = 0.3  # bin volume < lvn_mult * mean(bins) = a low-volume node (void)
    _bins: dict[int, float] = field(default_factory=dict, init=False)

    def _idx(self, price: float) -> int:
        return round(price / self.bucket)

    def price_of(self, idx: int) -> float:
        return round(idx * self.bucket, 4)

    def add(self, price: float, size: float | None) -> None:
        if size is None or size <= 0:
            return
        idx = self._idx(price)
        self._bins[idx] = self._bins.get(idx, 0.0) + size

    @property
    def total(self) -> float:
        return sum(self._bins.values())

    def mean_bin(self) -> float:
        """Average volume across occupied bins — the HVN/LVN reference level."""
        return self.total / len(self._bins) if self._bins else 0.0

    def poc(self) -> float | None:
        """Price of the heaviest bin (the point of control), or ``None`` if empty."""
        if not self._bins:
            return None
        return self.price_of(max(self._bins, key=lambda i: self._bins[i]))

    def value_area(self) -> tuple[float, float] | None:
        """``(VAL, VAH)`` — the price band holding ``value_area_pct`` of total volume.

        Grows out from the POC bin, each step extending toward whichever side still
        holds more *remaining* volume (annexing empty bins as zeros, so an LVN void
        between two nodes lands *inside* the area, as it should), until the band's
        volume reaches the target. A simplification of the classic two-bin TPO rule —
        adequate for telemetry and re-derivable offline. ``None`` if empty.
        """
        if not self._bins:
            return None
        target = self.total * self.value_area_pct
        poc_idx = max(self._bins, key=lambda i: self._bins[i])
        lo = hi = poc_idx
        acc = self._bins[poc_idx]
        while acc < target:
            above = sum(v for i, v in self._bins.items() if i > hi)
            below = sum(v for i, v in self._bins.items() if i < lo)
            if above <= 0 and below <= 0:
                break  # annexed all volume there is
            if above >= below:
                hi += 1
                acc += self._bins.get(hi, 0.0)
            else:
                lo -= 1
                acc += self._bins.get(lo, 0.0)
        return self.price_of(lo), self.price_of(hi)

    def classify(self, price: float) -> str:
        """``"HVN"`` / ``"LVN"`` / ``"normal"`` for the bin holding ``price``."""
        if not self._bins:
            return "empty"
        mean = self.mean_bin()
        vol = self._bins.get(self._idx(price), 0.0)
        if vol >= self.hvn_mult * mean:
            return "HVN"
        if vol < self.lvn_mult * mean:
            return "LVN"
        return "normal"

    def break_side_read(self, wall: float, side: str, reach: float) -> str:
        """Classify the far side of a wall *relative to the setup side*, over ``reach``.

        ``side="resistance"`` → the break side is above the wall (and the setup side
        below); ``"support"`` mirrors. Compares the mean bin volume in the ``span`` bins
        just outside the wall to the ``span`` bins just inside it: a break into *thinner
        air than where price has been* has runway. The candidate runner-leg signal —
        ``"void"`` (outside/inside < ``lvn_mult`` → runway, expect a runner) vs ``"hvn"``
        (outside/inside ≥ ``hvn_mult`` → a volume wall ahead, expect a stall/retest) vs
        ``"mixed"``. **Computed here, used by nothing** — instrumented so the upcoming
        sessions can show whether it separates the runaway (6/24) from the
        oscillating-box (6/29) case. ``"empty"`` when the setup side has no volume yet.
        """
        if not self._bins:
            return "empty"
        out_sign = 1 if side == "resistance" else -1
        wall_idx = self._idx(wall)
        span = max(1, round(reach / self.bucket))
        outside = sum(self._bins.get(wall_idx + out_sign * k, 0.0) for k in range(1, span + 1))
        inside = sum(self._bins.get(wall_idx - out_sign * k, 0.0) for k in range(1, span + 1))
        if inside <= 0:
            return "empty"  # no setup-side context to compare against
        ratio = outside / inside
        if ratio < self.lvn_mult:
            return "void"
        if ratio >= self.hvn_mult:
            return "hvn"
        return "mixed"

    def snapshot(self) -> dict[str, object]:
        """Lean dict for the shadow log — the histogram itself is rebuilt from the tape."""
        va = self.value_area()
        return {
            "total_vol": round(self.total, 1),
            "n_bins": len(self._bins),
            "poc": self.poc(),
            "val": va[0] if va else None,
            "vah": va[1] if va else None,
        }


@dataclass(slots=True)
class VolumeRate:
    """Trailing-window executed-volume rate vs a time-decayed baseline.

    Fed ``(size, ms)`` per print. Keeps prints within ``window_s`` of the latest ms;
    :meth:`rate` is the summed volume in that trailing window. ``_baseline`` is an
    exponential moving average of the window volume, decayed by wall-clock gaps with
    ``baseline_halflife_s``; :meth:`ratio` = rate / baseline (>1 expanding, <1
    contracting). The ratio is the **lower-priority** confidence idea — telemetry only,
    never a gate. Prints without an ``ms`` are ignored (the Tradier tape always carries
    one); a degrade, not a crash.
    """

    window_s: float = 60.0
    baseline_halflife_s: float = 300.0
    _events: deque[tuple[int, float]] = field(default_factory=deque, init=False)
    _window_vol: float = field(default=0.0, init=False)
    _baseline: float | None = field(default=None, init=False)
    _last_ms: int | None = field(default=None, init=False)

    def add(self, size: float | None, ms: int | None) -> None:
        if size is None or size <= 0 or ms is None:
            return
        self._events.append((ms, size))
        self._window_vol += size
        cutoff = ms - int(self.window_s * 1000)
        while self._events and self._events[0][0] < cutoff:
            self._window_vol -= self._events.popleft()[1]
        if self._baseline is None:
            self._baseline = self._window_vol
        elif self._last_ms is not None and ms > self._last_ms:
            dt = (ms - self._last_ms) / 1000.0
            alpha = 1.0 - 0.5 ** (dt / self.baseline_halflife_s)
            self._baseline += alpha * (self._window_vol - self._baseline)
        self._last_ms = ms

    def rate(self) -> float:
        return round(self._window_vol, 1)

    def baseline(self) -> float | None:
        return round(self._baseline, 1) if self._baseline is not None else None

    def ratio(self) -> float | None:
        if not self._baseline:
            return None
        return round(self._window_vol / self._baseline, 3)

    def snapshot(self) -> dict[str, object]:
        return {"rate": self.rate(), "baseline": self.baseline(), "ratio": self.ratio()}
