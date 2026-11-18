"""Named profiles: ~/.config/monctl/profiles.json.

{"Gaming": {"MAG323UPF": {"game_mode": "fps", ...}, "VX3418-2KPC": {"brightness": 60}}}
"""

from __future__ import annotations

import json
from pathlib import Path

from . import runner, settings
from .monitors import Monitor


def path() -> Path:
    return settings.config_dir() / "profiles.json"


def load() -> dict[str, dict]:
    try:
        data = json.loads(path().read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(data: dict) -> None:
    path().parent.mkdir(parents=True, exist_ok=True)
    path().write_text(json.dumps(data, indent=2) + "\n")


def capture(mons: list[Monitor]) -> dict[str, dict]:
    """Current settings of every monitor, limited to the keys a profile stores."""
    out = {}
    for m in mons:
        st = m.state()
        out[m.key] = {k: st[k] for k in m.profile_keys if k in st}
    return out


def save(name: str, mons: list[Monitor]) -> dict:
    data = load()
    data[name] = capture(mons)
    _save(data)
    return data[name]


def delete(name: str) -> bool:
    data = load()
    if data.pop(name, None) is None:
        return False
    _save(data)
    return True


def apply(name: str, mons: list[Monitor]) -> list[str]:
    """Apply a profile; return warnings (missing monitors, failures)."""
    prof = load().get(name)
    if prof is None:
        raise KeyError(name)
    by_key = {m.key: m for m in mons}
    warnings = []
    for key, values in prof.items():
        m = by_key.get(key)
        if m is None:
            warnings.append(f"{key}: not connected, skipped")
            continue
        try:
            m.apply(values)
        except runner.ToolError as e:
            warnings.append(f"{key}: {e}")
    return warnings
