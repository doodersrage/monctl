"""DDC/CI monitor control through ddcutil."""

from __future__ import annotations

from dataclasses import dataclass

from . import runner

VCP = {"brightness": "10", "contrast": "12"}


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


def parse_getvcp(text: str) -> dict[str, int]:
    codes = {v: k for k, v in VCP.items()}
    vals = {}
    for ln in text.splitlines():
        p = ln.split()
        if len(p) >= 4 and p[0] == "VCP" and p[1].upper() in codes and p[2] == "C":
            vals[codes[p[1].upper()]] = int(p[3])
    return vals


def get(bus: int) -> dict[str, int]:
    return parse_getvcp(runner.run(["ddcutil", "--bus", str(bus), "getvcp", *VCP.values(), "--brief"]))


def apply(bus: int, values: dict) -> None:
    for name, val in values.items():
        if name not in VCP:
            raise runner.ToolError(f"{name} is not supported over DDC/CI (only {', '.join(VCP)})")
        v = int(val)
        if not 0 <= v <= 100:
            raise runner.ToolError(f"{name} must be 0-100, got {val!r}")
    for name, val in values.items():
        runner.run(["ddcutil", "--bus", str(bus), "setvcp", VCP[name], str(int(val))])
