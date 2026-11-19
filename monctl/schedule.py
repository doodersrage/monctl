"""Time-of-day profiles: "schedule": [{"at": "07:30", "profile": "Desktop"}, {"at": "21:00", "profile": "Night"}]

A scheduled profile is applied when its time passes (also when it passed while the PC slept).
Nothing is applied at startup, so a profile chosen by hand stays until the next scheduled time.
The schedule also decides which profile automatic profiles return to after a game exits:
the slot that is current at that moment (instead of auto_default).
"""

from __future__ import annotations

import datetime as dt
import re

from . import settings

_HHMM = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


def parse(at: str) -> dt.time:
    m = _HHMM.match(at.strip())
    if not m:
        raise ValueError(f"time must be HH:MM, got {at!r}")
    return dt.time(int(m.group(1)), int(m.group(2)))


def entries(cfg: dict | None = None) -> list[tuple[dt.time, str]]:
    raw = (cfg if cfg is not None else settings.load()).get("schedule") or []
    out = []
    for e in raw:
        try:
            out.append((parse(e["at"]), e["profile"]))
        except (KeyError, TypeError, ValueError):
            continue
    return sorted(out)


def current(now: dt.datetime, cfg: dict | None = None) -> str | None:
    """The profile whose slot contains `now` (the last entry before it, wrapping to yesterday)."""
    es = entries(cfg)
    if not es:
        return None
    before = [p for t, p in es if t <= now.time()]
    return before[-1] if before else es[-1][1]


def crossed(since: dt.datetime, now: dt.datetime, cfg: dict | None = None) -> str | None:
    """The profile of the latest scheduled time in (since, now], or None."""
    es = entries(cfg)
    if not es or now <= since:
        return None
    hit = None
    day = max(since.date(), now.date() - dt.timedelta(days=1))   # asleep for days: last two suffice
    while day <= now.date():
        for t, p in es:
            if since < dt.datetime.combine(day, t) <= now:
                hit = p                    # entries are sorted, so the last match is the latest
        day += dt.timedelta(days=1)
    return hit


class Scheduler:
    def __init__(self, clock=dt.datetime.now):
        self.clock = clock
        self.last = clock()

    def tick(self, cfg: dict | None = None) -> str | None:
        now = self.clock()
        hit = crossed(self.last, now, cfg)
        self.last = now
        return hit


def add(at: str, profile: str) -> list[dict]:
    t = parse(at).strftime("%H:%M")
    rows = [e for e in settings.get("schedule") if e.get("at") != t] + [{"at": t, "profile": profile}]
    rows.sort(key=lambda e: e["at"])
    settings.set(schedule=rows)
    return rows


def remove(at: str) -> bool:
    t = parse(at).strftime("%H:%M")
    rows = settings.get("schedule")
    left = [e for e in rows if e.get("at") != t]
    settings.set(schedule=left)
    return len(left) != len(rows)
