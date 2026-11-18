"""monctl's own settings: ~/.config/monctl/settings.json."""

from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULTS = {
    "msigd": "",        # path to the msigd binary; "" = $MONCTL_MSIGD or msigd on PATH
    "auto_enabled": False,  # automatic profiles (see autoprofile.py)
    "auto_default": "",     # profile applied when the last matching app exits
    "auto_rules": [],       # [{"match": "steam:game" | process name, "profile": name}]
}


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "monctl"


def path() -> Path:
    return config_dir() / "settings.json"


def load() -> dict:
    s = {k: (list(v) if isinstance(v, list) else v) for k, v in DEFAULTS.items()}
    try:
        data = json.loads(path().read_text())
        if isinstance(data, dict):
            s.update({k: v for k, v in data.items() if k in DEFAULTS})
    except (OSError, ValueError):
        pass
    return s


def get(key: str):
    return load()[key]


def set(**values) -> dict:  # noqa: A001 - module-level API, used as settings.set(...)
    unknown = [k for k in values if k not in DEFAULTS]
    if unknown:
        raise KeyError(f"unknown setting(s): {', '.join(unknown)}")
    s = load()
    s.update(values)
    path().parent.mkdir(parents=True, exist_ok=True)
    path().write_text(json.dumps(s, indent=2) + "\n")
    return s
