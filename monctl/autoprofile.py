"""Automatic profiles: switch profile while a matching app runs.

Rules live in settings.json:
  "auto_enabled": true,
  "auto_default": "Desktop",                 # applied when the last matching app exits
  "auto_rules": [{"match": "steam:game", "profile": "Gaming"},
                 {"match": "blender", "profile": "Work"}]

A rule's "match" is a process name (case-insensitive; ".exe" optional, so
Proton/Wine games match by their Windows executable name) or "steam:game" for
any game launched by Steam. The first matching rule wins.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from . import settings

STEAM_GAME = "steam:game"
# Steam client processes; they are not games even if they carry a Steam app id.
STEAM_CLIENT = {"steam", "steamwebhelper", "steam.sh", "steam-runtime-l", "steam-runtime-launcher-service",
                "srt-logger", "pressure-vessel-", "pv-bwrap"}


def _norm(name: str) -> str:
    name = name.strip().lower().replace("\\", "/").rsplit("/", 1)[-1]
    return name[:-4] if name.endswith(".exe") else name


@dataclass
class Proc:
    pid: int
    names: set[str] = field(default_factory=set)
    steam_app: str = ""

    @property
    def steam_game(self) -> bool:
        return bool(self.steam_app) and self.steam_app != "0" and not (self.names & STEAM_CLIENT)


def _read(path: Path, limit: int = 1 << 16) -> bytes:
    try:
        with open(path, "rb") as f:
            return f.read(limit)
    except OSError:
        return b""


def read_proc(pid: int, root: Path = Path("/proc")) -> Proc | None:
    base = root / str(pid)
    comm = _read(base / "comm").decode(errors="replace").strip()
    if not comm:
        return None
    names = {_norm(comm)}
    argv0 = _read(base / "cmdline", 4096).split(b"\0", 1)[0].decode(errors="replace")
    argv0 = argv0.split(" -", 1)[0]   # some apps (Electron) rewrite argv into one string
    if argv0:
        names.add(_norm(argv0))
    steam = ""
    for var in _read(base / "environ").split(b"\0"):
        k, _, v = var.partition(b"=")
        if k in (b"SteamGameId", b"SteamAppId") and v:
            steam = v.decode(errors="replace")
            break
    names.discard("")
    return Proc(pid, names, steam)


class Scanner:
    """Lists the user's processes, caching per pid (a pid's comm/env rarely change)."""

    def __init__(self, root: Path = Path("/proc")):
        self.root = root
        self.cache: dict[int, Proc] = {}
        self.uid = os.getuid()

    def scan(self) -> list[Proc]:
        pids = set()
        for d in self.root.iterdir():
            if not d.name.isdigit():
                continue
            try:
                if d.stat().st_uid != self.uid:
                    continue
            except OSError:
                continue
            pids.add(int(d.name))
        for pid in list(self.cache):
            if pid not in pids:
                del self.cache[pid]
        for pid in pids - self.cache.keys():
            p = read_proc(pid, self.root)
            if p:
                self.cache[pid] = p
        return list(self.cache.values())


def rule_matches(match: str, procs: list[Proc]) -> bool:
    if match == STEAM_GAME:
        return any(p.steam_game for p in procs)
    want = _norm(match)
    return any(want in p.names for p in procs)


def pick(rules: list[dict], procs: list[Proc]) -> str | None:
    for r in rules:
        if r.get("match") and r.get("profile") and rule_matches(r["match"], procs):
            return r["profile"]
    return None


class Watcher:
    """Applies a profile when the winning rule changes.

    Nothing happens at startup when no rule matches, so a manually chosen
    profile is left alone until an app actually starts or stops.
    """

    def __init__(self, apply, scanner: Scanner | None = None):
        self.apply = apply
        self.scanner = scanner or Scanner()
        self.active: str | None = None

    def tick(self, cfg: dict | None = None) -> str | None:
        """Scan once; return the profile applied, if any."""
        cfg = cfg or settings.load()
        if not cfg.get("auto_enabled"):
            self.active = None
            return None
        target = pick(cfg.get("auto_rules") or [], self.scanner.scan())
        if target == self.active:
            return None
        previous, self.active = self.active, target
        profile = target or (cfg.get("auto_default") if previous else None) or None
        if profile:
            self.apply(profile)
        return profile


def running_names(procs: list[Proc]) -> list[str]:
    """Process names worth offering in a picker (no kernel threads/helpers)."""
    skip = {"bash", "sh", "zsh", "fish", "sudo", "systemd", "dbus-daemon", "kworker"}
    names = set()
    for p in procs:
        names |= {n for n in p.names if n not in skip and not n.startswith(("kworker", "("))}
    return sorted(names)
