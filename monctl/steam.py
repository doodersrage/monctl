"""Installed Steam games, read from Steam's library files (no Steam API needed).

A rule "steam:<appid>" matches that game only: Steam gives every process of a game its app id
(SteamAppId/SteamGameId environment, or `reaper SteamLaunch AppId=<id>`).
"""

from __future__ import annotations

import os
import re
from pathlib import Path

PREFIX = "steam:"
# Steam tools that install like games but never are one
_TOOLS = re.compile(r"^(Proton\b|Steam Linux Runtime|Steamworks Common|Steamworks Shared|SteamVR)", re.I)
_PAIR = re.compile(r'"((?:[^"\\]|\\.)*)"\s+"((?:[^"\\]|\\.)*)"')


def steam_roots() -> list[Path]:
    home = Path.home()
    cands = [home / ".local/share/Steam", home / ".steam/steam",
             home / ".var/app/com.valvesoftware.Steam/.local/share/Steam"]
    if os.environ.get("MONCTL_STEAM_ROOT"):
        cands.insert(0, Path(os.environ["MONCTL_STEAM_ROOT"]))
    seen, out = set(), []
    for c in cands:
        try:
            r = c.resolve()
        except OSError:
            continue
        if r.is_dir() and r not in seen:
            seen.add(r)
            out.append(r)
    return out


def _pairs(text: str) -> list[tuple[str, str]]:
    return [(k, v.replace("\\\\", "\\")) for k, v in _PAIR.findall(text)]


def library_dirs(root: Path) -> list[Path]:
    dirs = [root / "steamapps"]
    try:
        text = (root / "steamapps" / "libraryfolders.vdf").read_text(errors="replace")
    except OSError:
        return dirs
    for k, v in _pairs(text):
        if k == "path":
            d = Path(v) / "steamapps"
            if d not in dirs:
                dirs.append(d)
    return dirs


def parse_manifest(text: str) -> tuple[str, str] | None:
    vals = dict(_pairs(text))
    appid, name = vals.get("appid", ""), vals.get("name", "")
    if not appid.isdigit() or not name or _TOOLS.match(name):
        return None
    return appid, name


def installed_games() -> dict[str, str]:
    """app id -> game name, sorted by name."""
    games: dict[str, str] = {}
    for root in steam_roots():
        for d in library_dirs(root):
            for f in d.glob("appmanifest_*.acf"):
                try:
                    hit = parse_manifest(f.read_text(errors="replace"))
                except OSError:
                    continue
                if hit:
                    games[hit[0]] = hit[1]
    return dict(sorted(games.items(), key=lambda kv: kv[1].lower()))


def app_id(match: str) -> str | None:
    """"steam:1091500" -> "1091500"; None for other matches (incl. "steam:game")."""
    if match.startswith(PREFIX) and match[len(PREFIX):].isdigit():
        return match[len(PREFIX):]
    return None
