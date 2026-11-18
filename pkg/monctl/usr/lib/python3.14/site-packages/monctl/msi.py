"""MSI monitor OSD settings over USB, through the msigd command-line tool.

Only settings whose writes were verified on hardware are writable, and some
values are refused outright (see REFUSED). Everything else is read-only.
"""

from __future__ import annotations

import os
import shutil

from . import runner, settings

PCT = "0-100"

# Writable settings and their allowed values. Verified on a MAG323UPF (FW V61):
# each was written, read back and restored with a full-state diff afterwards.
WRITABLE: dict[str, object] = {
    "brightness": PCT,
    "contrast": PCT,
    "game_mode": ["user", "fps", "racing", "rts", "rpg"],
    "night_vision": ["off", "normal", "strong", "strongest", "ai"],
    "smart_crosshair_icon": ["off", "icon1", "icon2", "icon3", "icon4", "icon5", "icon6"],
    "smart_crosshair_color": ["white", "red", "auto"],
    "response_time": ["normal", "fast", "fastest"],
    "eye_saver": ["off", "on"],
    "input": ["hdmi1", "hdmi2", "dp", "usbc"],
    "kvm": ["auto", "upstream"],
    "auto_scan": ["off", "on"],
    "hdmi_cec": ["off", "on"],
    "power_button": ["off", "standby"],
}

# Values/settings monctl will never send, with the reason shown to the user.
REFUSED = {
    ("kvm", "type_c"): "the monitor's USB control channel sits on its own hub; switching KVM to "
                       "USB-C disconnects it and only the OSD can switch back",
    ("pip", None): "turning PiP on resets brightness, response time, Adaptive-Sync and Zero "
                   "Latency, which can't all be restored over USB; use the OSD",
    ("free_sync", None): "writing this code hung other MSI models; use the OSD",
    ("zero_latency", None): "writing this code is unverified and risky; use the OSD",
}

# Order matters: game_mode applies a preset that overwrites brightness etc.,
# so it is always sent first, in its own call.
FIRST = ("game_mode",)


class MsiError(runner.ToolError):
    pass


def binary() -> str | None:
    for cand in (settings.get("msigd"), os.environ.get("MONCTL_MSIGD"), shutil.which("msigd")):
        if cand and os.access(cand, os.X_OK):
            return cand
    return None


def _msigd(*args: str, timeout: float = 30) -> str:
    exe = binary()
    if not exe:
        raise MsiError("msigd not found (install it, or: monctl config msigd /path/to/msigd)")
    return runner.run([exe, *args], timeout=timeout)


def available() -> bool:
    """True when msigd is installed and at least one MSI monitor answers."""
    try:
        return bool(list_devices())
    except runner.ToolError:
        return False


def list_devices() -> list[str]:
    out = _msigd("--list")
    return [ln for ln in out.splitlines() if ln[:1].isdigit()]


def parse_query(text: str) -> dict[str, str]:
    vals = {}
    for ln in text.splitlines():
        name, sep, value = ln.partition(" : ")
        if sep and name and " " not in name.strip():
            vals[name.strip()] = value.strip()
    return vals


def query(monitor: int = 1) -> dict[str, str]:
    return parse_query(_msigd("--monitor", str(monitor), "--query"))


def info(monitor: int = 1) -> dict[str, str]:
    out = _msigd("--monitor", str(monitor), "--info")
    vals = {}
    for ln in out.splitlines():
        k, sep, v = ln.partition(":")
        if sep:
            vals[k.strip()] = v.strip()
    return vals


def check(name: str, value) -> str:
    """Validate one setting; return the value as msigd expects it, or raise MsiError."""
    value = str(value).strip().lower()
    for key in ((name, value), (name, None)):
        if key in REFUSED:
            raise MsiError(f"refusing {name}={value}: {REFUSED[key]}")
    allowed = WRITABLE.get(name)
    if allowed is None:
        raise MsiError(f"{name} is not writable from monctl")
    if allowed == PCT:
        if not value.isdigit() or not 0 <= int(value) <= 100:
            raise MsiError(f"{name} must be 0-100, got {value!r}")
        return str(int(value))
    if value not in allowed:
        raise MsiError(f"{name} must be one of {', '.join(allowed)}; got {value!r}")
    return value


def apply(values: dict, monitor: int = 1) -> None:
    """Write settings. All values are validated before anything is sent."""
    checked = {k: check(k, v) for k, v in values.items()}
    first = {k: v for k, v in checked.items() if k in FIRST}
    rest = {k: v for k, v in checked.items() if k not in FIRST}
    for batch in (first, rest):
        if batch:
            args = ["--monitor", str(monitor)]
            for k, v in batch.items():
                args += [f"--{k}", v]
            _msigd(*args)
