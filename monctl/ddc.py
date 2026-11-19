"""DDC/CI monitor control through ddcutil."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from . import runner

VCP = {"brightness": "10", "contrast": "12"}
INPUT_VCP = "60"
# MCCS input source codes (VCP 0x60); names match msigd's where they overlap
INPUT_NAMES = {0x01: "vga1", 0x02: "vga2", 0x03: "dvi1", 0x04: "dvi2", 0x0f: "dp1", 0x10: "dp2",
               0x11: "hdmi1", 0x12: "hdmi2", 0x1b: "usbc"}
INPUT_CODES = {v: k for k, v in INPUT_NAMES.items()}
# Models that list VCP 60 and accept writes but never switch (tested on hardware): no Input control.
INPUT_IGNORED = {"U28E590"}   # Samsung U28E590: also reports its input as 0x09 "Tuner-1"


@dataclass
class Display:
    bus: int
    connector: str      # e.g. "DP-1"
    mfg: str            # three-letter EDID code, e.g. "MSI"
    model: str
    serial: str


def parse_detect(text: str) -> list[Display]:
    out, cur = [], None
    for raw in text.splitlines():
        ln = raw.strip()
        if raw.startswith("Display "):
            cur = {}
            out.append(cur)
            continue
        if not raw.startswith((" ", "\t")):
            cur = None          # "Invalid display" and other blocks
            continue
        if cur is None:
            continue
        key, _, val = ln.partition(":")
        cur[key.strip()] = val.strip()
    displays = []
    for d in out:
        bus = d.get("I2C bus", "").rsplit("-", 1)[-1]
        if not bus.isdigit():
            continue
        mon = d.get("Monitor", "").split(":")
        mon += [""] * (3 - len(mon))
        serial = mon[2] if mon[2].isascii() and mon[2].isprintable() else ""
        conn = d.get("DRM connector", "").split("-", 1)[-1]
        displays.append(Display(int(bus), conn, mon[0], mon[1], serial.strip()))
    return displays


def detect() -> list[Display]:
    return parse_detect(runner.run(["ddcutil", "detect", "--brief"], timeout=60))


def parse_getvcp(text: str) -> dict:
    codes = {v: k for k, v in VCP.items()}
    vals: dict = {}
    for ln in text.splitlines():
        p = ln.split()
        if len(p) >= 4 and p[0] == "VCP" and p[1].upper() in codes and p[2] == "C":
            vals[codes[p[1].upper()]] = int(p[3])
        elif len(p) >= 4 and p[0] == "VCP" and p[1] == INPUT_VCP and p[2] == "SNC":
            # some monitors (Samsung) report a code they don't list, e.g. x09: show it as unknown
            vals["input"] = INPUT_NAMES.get(int(p[3].lstrip("x"), 16), "")
    return vals


def get(bus: int) -> dict:
    return parse_getvcp(runner.run(["ddcutil", "--bus", str(bus), "getvcp", *VCP.values(), INPUT_VCP,
                                    "--brief"]))


def parse_input_caps(text: str) -> list[str]:
    """Input names listed under "Feature: 60" in `ddcutil capabilities`."""
    out, inside = [], False
    for ln in text.splitlines():
        m = re.match(r"\s*Feature: ([0-9A-Fa-f]{2})\b", ln)
        if m:
            inside = m.group(1) == INPUT_VCP
            continue
        v = re.match(r"\s*([0-9A-Fa-f]{2}):", ln)
        if inside and v and int(v.group(1), 16) in INPUT_NAMES:
            out.append(INPUT_NAMES[int(v.group(1), 16)])
    return out


def _cache(key: str) -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "monctl" / f"inputs-{re.sub(r'[^A-Za-z0-9_.-]', '_', key)}.json"


def inputs(bus: int, key: str) -> list[str]:
    """The monitor's inputs; the capabilities query takes seconds, so it is cached per model."""
    if key in INPUT_IGNORED:
        return []
    try:
        return json.loads(_cache(key).read_text())
    except (OSError, ValueError):
        pass
    names = parse_input_caps(runner.run(["ddcutil", "--bus", str(bus), "capabilities"], timeout=60))
    if names:
        _cache(key).parent.mkdir(parents=True, exist_ok=True)
        _cache(key).write_text(json.dumps(names))
    return names


def apply(bus: int, values: dict, allowed_inputs: list[str] | None = None) -> None:
    for name, val in values.items():
        if name == "input":
            if val not in (allowed_inputs or []):
                raise runner.ToolError(f"input must be one of {', '.join(allowed_inputs or []) or '(none)'}, "
                                       f"got {val!r}")
            continue
        if name not in VCP:
            raise runner.ToolError(f"{name} is not supported over DDC/CI (only {', '.join([*VCP, 'input'])})")
        v = int(val)
        if not 0 <= v <= 100:
            raise runner.ToolError(f"{name} must be 0-100, got {val!r}")
    for name, val in values.items():
        if name == "input":
            runner.run(["ddcutil", "--bus", str(bus), "setvcp", INPUT_VCP, f"x{INPUT_CODES[val]:02x}"])
        else:
            runner.run(["ddcutil", "--bus", str(bus), "setvcp", VCP[name], str(int(val))])
