"""Unified view of the connected monitors.

Monitors come from ddcutil. An MSI monitor is controlled through msigd (USB)
when msigd finds one; everything else uses DDC/CI.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import ddc, msi, runner

MSI_PROFILE_KEYS = ("game_mode", "brightness", "contrast", "night_vision", "smart_crosshair_icon",
                    "smart_crosshair_color", "response_time", "eye_saver")
DDC_PROFILE_KEYS = tuple(ddc.VCP)


@dataclass
class Monitor:
    key: str                 # stable name used in profiles, e.g. "MAG323UPF"
    label: str               # "MSI MAG323UPF (DP-3)"
    connector: str = ""
    bus: int | None = None   # DDC/CI i2c bus
    msi: int | None = None   # msigd monitor number when controlled over USB
    extra: dict = field(default_factory=dict)

    @property
    def backend(self) -> str:
        return "msigd" if self.msi else "ddc"

    @property
    def profile_keys(self) -> tuple[str, ...]:
        return MSI_PROFILE_KEYS if self.msi else DDC_PROFILE_KEYS

    def state(self) -> dict:
        if self.msi:
            return msi.query(self.msi)
        if self.bus is None:
            raise runner.ToolError(f"{self.label}: no DDC/CI bus")
        return ddc.get(self.bus)

    @property
    def inputs(self) -> list[str]:
        """Selectable inputs (values for apply({"input": ...}))."""
        if self.msi:
            return list(msi.WRITABLE["input"])
        if self.bus is None:
            return []
        return ddc.inputs(self.bus, self.key)

    def apply(self, values: dict) -> None:
        if self.msi:
            msi.apply(values, self.msi)
        elif self.bus is not None:
            ddc.apply(self.bus, values, self.inputs if "input" in values else None)
        else:
            raise runner.ToolError(f"{self.label}: no DDC/CI bus")


def discover() -> list[Monitor]:
    try:
        displays = ddc.detect()
    except runner.ToolError:
        displays = []
    has_msi = msi.available()
    mons: list[Monitor] = []
    msi_used = False
    for d in displays:
        is_msi = has_msi and d.mfg == "MSI" and not msi_used
        model = d.model.removeprefix("MSI ").strip() or f"{d.mfg}-{d.connector}"
        mons.append(Monitor(key=model, label=f"{d.mfg} {model} ({d.connector})",
                            connector=d.connector, bus=d.bus, msi=1 if is_msi else None))
        msi_used |= is_msi
    if has_msi and not msi_used:  # MSI found over USB but not over DDC/CI
        series = msi.info(1).get("Monitor Series", "MSI")
        mons.append(Monitor(key=series, label=f"MSI {series} (USB)", msi=1))
    # make keys unique if two identical models are connected
    seen: dict[str, int] = {}
    for m in mons:
        n = seen.get(m.key, 0)
        seen[m.key] = n + 1
        if n:
            m.key = f"{m.key}@{m.connector or n}"
    return mons


def find(mons: list[Monitor], name: str) -> list[Monitor]:
    """Match by index (1-based), key, connector, or 'all'."""
    if name == "all":
        return mons
    if name.isdigit() and 1 <= int(name) <= len(mons):
        return [mons[int(name) - 1]]
    low = name.lower()
    hits = [m for m in mons if low in (m.key.lower(), m.connector.lower())]
    return hits or [m for m in mons if low in m.label.lower()]
