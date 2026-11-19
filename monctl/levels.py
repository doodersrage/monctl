"""Brightness matching: one "all monitors" level, mapped into each monitor's own range.

settings.json:  "brightness_range": {"U28E590": [0, 80], "VX3418-2KPC": [5, 100]}

A monitor without an entry uses 0-100, so the level is sent unchanged. Calibrate by setting
every monitor to the same level (e.g. 50) and narrowing the range of the ones that look
brighter until they match. Per-monitor sliders and `monctl set` stay raw.
"""

from __future__ import annotations

from . import settings


def ranges() -> dict[str, list[int]]:
    r = settings.get("brightness_range")
    return r if isinstance(r, dict) else {}


def _range(key: str, rng: dict | None) -> tuple[int, int]:
    lo, hi = (rng if rng is not None else ranges()).get(key, (0, 100))
    return int(lo), int(hi)


def to_monitor(key: str, level: int, rng: dict | None = None) -> int:
    lo, hi = _range(key, rng)
    level = max(0, min(100, int(level)))
    return round(lo + (hi - lo) * level / 100)


def to_level(key: str, value, rng: dict | None = None) -> int | None:
    """The "all monitors" level a monitor's raw brightness corresponds to."""
    try:
        value = int(value)
    except (TypeError, ValueError):
        return None
    lo, hi = _range(key, rng)
    if hi == lo:
        return 100 if value >= hi else 0
    return max(0, min(100, round((value - lo) * 100 / (hi - lo))))


def set_range(key: str, lo: int | None, hi: int | None) -> dict:
    """Set a monitor's range; None for both resets it to 0-100."""
    r = dict(ranges())
    if lo is None and hi is None:
        r.pop(key, None)
    else:
        lo, hi = int(lo), int(hi)
        if not 0 <= lo < hi <= 100:
            raise ValueError("range must satisfy 0 <= low < high <= 100")
        r[key] = [lo, hi]
    settings.set(brightness_range=r)
    return r
