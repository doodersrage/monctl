"""Notice monitors coming and going, and resume from sleep, without extra dependencies.

Polled from the tray/watch timers:
  * DRM connector status (/sys/class/drm/card*-*/status) for every display,
  * the MSI monitor's USB HID node (vendor 1462 under /sys/class/hidraw),
  * a jump between CLOCK_BOOTTIME and CLOCK_MONOTONIC, which only happens across suspend.
"""

from __future__ import annotations

import time
from pathlib import Path

MSI_VENDOR = "00001462"
RESUME_JUMP = 2.0  # seconds asleep before we call it a resume


def _read(p: Path) -> str:
    try:
        return p.read_text().strip()
    except OSError:
        return ""


def _sleep_offset() -> float:
    return time.clock_gettime(time.CLOCK_BOOTTIME) - time.clock_gettime(time.CLOCK_MONOTONIC)


class Hotplug:
    def __init__(self, sys_root: Path = Path("/sys"), clock=_sleep_offset):
        self.sys = sys_root
        self.clock = clock
        self.last: tuple | None = None
        self.offset = clock()

    def snapshot(self) -> tuple:
        drm = tuple(sorted((p.parent.name, _read(p)) for p in (self.sys / "class" / "drm").glob("card*-*/status")))
        hid = []
        for d in sorted((self.sys / "class" / "hidraw").glob("hidraw*")):
            for line in _read(d / "device" / "uevent").splitlines():
                if line.startswith("HID_ID=") and line.split(":")[1:2] == [MSI_VENDOR]:
                    hid.append(d.name)
        return drm, tuple(hid)

    def tick(self) -> str | None:
        """Return "resumed" or "monitors changed" when something happened since the last tick."""
        offset = self.clock()
        resumed = offset - self.offset > RESUME_JUMP
        self.offset = offset
        snap = self.snapshot()
        changed = self.last is not None and snap != self.last
        self.last = snap
        if resumed:
            return "resumed"
        return "monitors changed" if changed else None
