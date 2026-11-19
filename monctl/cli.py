"""monctl command line."""

from __future__ import annotations

import argparse
import json
import sys

from . import __version__, autoprofile, levels, msi, profiles, runner, schedule, settings
from .monitors import Monitor, discover, find


def _err(msg: str) -> int:
    print(f"monctl: {msg}", file=sys.stderr)
    return 1


def _pick(mons: list[Monitor], name: str) -> list[Monitor]:
    hits = find(mons, name)
    if not hits:
        raise runner.ToolError(f"no monitor matches {name!r} (see: monctl list)")
    return hits


def cmd_list(a, mons):
    if not mons:
        return _err("no monitors found (is ddcutil installed and i2c-dev loaded?)")
    for i, m in enumerate(mons, 1):
        print(f"{i}  {m.label:34} key={m.key:14} via {m.backend}")
    return 0


def cmd_status(a, mons):
    for m in _pick(mons, a.monitor):
        st = m.state()
        if a.json:
            print(json.dumps({m.key: st}))
            continue
        print(f"{m.label}  [{m.backend}]")
        keys = st if a.all else [k for k in m.profile_keys if k in st]
        for k in keys:
            flag = "" if not m.msi or k in msi.WRITABLE else "  (read-only)"
            print(f"  {k:22} {st[k]}{flag}")
    return 0


def _pairs(items: list[str]) -> dict:
    vals = {}
    for it in items:
        k, sep, v = it.partition("=")
        if not sep or not k:
            raise runner.ToolError(f"expected key=value, got {it!r}")
        vals[k.strip()] = v.strip()
    return vals


def cmd_set(a, mons):
    vals = _pairs(a.values)
    for m in _pick(mons, a.monitor):
        m.apply(vals)
        print(f"{m.label}: " + ", ".join(f"{k}={v}" for k, v in vals.items()))
    return 0


def cmd_brightness(a, mons):
    # "all" uses brightness matching (monctl range); a named monitor gets the raw value
    matched = a.monitor == "all"
    for m in _pick(mons, a.monitor):
        v = levels.to_monitor(m.key, a.value) if matched else a.value
        m.apply({"brightness": v})
        print(f"{m.label}: brightness={v}")
    return 0


def cmd_range(a, _mons):
    if a.key and a.low == "reset":
        levels.set_range(a.key, None, None)
    elif a.key and a.low is not None and a.high is not None:
        try:
            levels.set_range(a.key, int(a.low), int(a.high))
        except ValueError as e:
            return _err(str(e))
    elif a.key:
        return _err("usage: monctl range KEY LOW HIGH  |  monctl range KEY reset")
    r = levels.ranges()
    if not r:
        print("all monitors use 0-100 (no matching set)")
    for k, (lo, hi) in sorted(r.items()):
        print(f"  {k:16} {lo:3}-{hi}")
    return 0


def cmd_schedule(a, _mons):
    try:
        if a.action == "add":
            if len(a.args) != 2:
                return _err("usage: monctl schedule add HH:MM PROFILE")
            if a.args[1] not in profiles.load():
                return _err(f"no profile {a.args[1]!r}")
            schedule.add(*a.args)
        elif a.action == "remove":
            if len(a.args) != 1 or not schedule.remove(a.args[0]):
                return _err("usage: monctl schedule remove HH:MM (an existing time)")
    except ValueError as e:
        return _err(str(e))
    rows = settings.get("schedule")
    for e in rows:
        print(f"  {e['at']}  -> {e['profile']}")
    if not rows:
        print("  (empty; add one with: monctl schedule add 21:00 Night)")
    return 0


def cmd_profile(a, mons):
    if a.action == "list":
        for name in profiles.load():
            print(name)
        return 0
    if not a.name:
        return _err(f"profile {a.action} needs a name")
    if a.action == "show":
        prof = profiles.load().get(a.name)
        if prof is None:
            return _err(f"no profile {a.name!r}")
        print(json.dumps(prof, indent=2))
    elif a.action == "save":
        prof = profiles.save(a.name, mons)
        print(f"saved {a.name!r}: " + ", ".join(prof))
    elif a.action == "delete":
        if not profiles.delete(a.name):
            return _err(f"no profile {a.name!r}")
        print(f"deleted {a.name!r}")
    elif a.action == "apply":
        try:
            warns = profiles.apply(a.name, mons)
        except KeyError:
            return _err(f"no profile {a.name!r}")
        for w in warns:
            print(f"warning: {w}", file=sys.stderr)
        print(f"applied {a.name!r}")
    return 0


def cmd_auto(a, _mons):
    cfg = settings.load()
    rules = cfg["auto_rules"]
    if a.action in ("on", "off"):
        settings.set(auto_enabled=a.action == "on")
    elif a.action == "default":
        if a.args and a.args[0] not in profiles.load():
            return _err(f"no profile {a.args[0]!r}")
        settings.set(auto_default=a.args[0] if a.args else "")
    elif a.action == "add":
        if len(a.args) != 2:
            return _err("usage: monctl auto add MATCH PROFILE [--focused]  (MATCH: process name or steam:game)")
        match, prof = a.args
        if prof not in profiles.load():
            return _err(f"no profile {prof!r}")
        rule = {"match": match, "profile": prof}
        if a.focused:
            rule["focused"] = True
        rules = [r for r in rules if r.get("match") != match] + [rule]
        settings.set(auto_rules=rules)
    elif a.action == "remove":
        if not a.args:
            return _err("usage: monctl auto remove MATCH")
        left = [r for r in rules if r.get("match") != a.args[0]]
        if len(left) == len(rules):
            return _err(f"no rule for {a.args[0]!r}")
        settings.set(auto_rules=left)
    elif a.action == "procs":
        procs = autoprofile.Scanner().scan()
        games = sorted({n for p in procs if p.steam_game for n in p.names})
        print("Steam games running: " + (", ".join(games) if games else "none"))
        print("\n".join(autoprofile.running_names(procs)))
        return 0
    cfg = settings.load()
    print(f"automatic profiles: {'on' if cfg['auto_enabled'] else 'off'}"
          f"   default: {cfg['auto_default'] or '(none)'}")
    for i, r in enumerate(cfg["auto_rules"], 1):
        print(f"  {i}. {r['match']:24} -> {r['profile']}{'   (only while focused)' if r.get('focused') else ''}")
    if not cfg["auto_rules"]:
        print("  (no rules; add one with: monctl auto add steam:game Gaming)")
    return 0


def cmd_watch(a, _mons):
    import time

    from . import hotplug
    unfinished: dict = {}          # profile name -> monitor keys it skipped

    def apply(name, only=None):
        skipped: set[str] = set()
        warns = profiles.apply(name, discover(), only=only, skipped=skipped)
        unfinished.clear()
        if skipped:
            unfinished[name] = skipped
        what = f" to {', '.join(sorted(only))}" if only else ""
        print(f"{time.strftime('%H:%M:%S')} applied {name!r}{what}", flush=True)
        for w in warns:
            print(f"  warning: {w}", file=sys.stderr, flush=True)

    if not settings.get("auto_enabled"):
        print("automatic profiles are off; enabling them for this session only", file=sys.stderr)
    w = autoprofile.Watcher(apply)
    hp = hotplug.Hotplug()
    sched = schedule.Scheduler()
    retry_at = None
    try:
        while True:
            cfg = settings.load()
            cfg["auto_enabled"] = True
            try:
                if hp.tick():
                    retry_at = time.monotonic() + 4      # let the monitor finish waking up
                if retry_at and time.monotonic() >= retry_at:
                    retry_at = None
                    for name, keys in list(unfinished.items()):
                        if name in profiles.load():
                            apply(name, only=keys)
                w.tick(cfg)
                due = sched.tick(cfg)
                if due and w.active is None and due in profiles.load():
                    apply(due)
            except runner.ToolError as e:
                print(f"monctl: {e}", file=sys.stderr, flush=True)
            time.sleep(a.interval)
    except KeyboardInterrupt:
        return 0


def cmd_config(a, _mons):
    if a.key is None:
        print(json.dumps(settings.load(), indent=2))
    elif a.value is None:
        print(settings.get(a.key))
    else:
        settings.set(**{a.key: a.value})
    return 0


def cmd_tray(a, _mons):
    from .qt import run_tray
    return run_tray(open_window=a.window)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="monctl", description="Monitor control: MSI over USB, others over DDC/CI.")
    p.add_argument("--version", action="version", version=f"monctl {__version__}")
    sub = p.add_subparsers(dest="cmd")

    sub.add_parser("list", help="list monitors").set_defaults(fn=cmd_list)

    s = sub.add_parser("status", help="show monitor settings")
    s.add_argument("monitor", nargs="?", default="all", help="index, key, connector or 'all'")
    s.add_argument("--all", action="store_true", help="include every setting msigd reports")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_status)

    s = sub.add_parser("set", help="change settings, e.g. monctl set MAG323UPF game_mode=fps")
    s.add_argument("monitor")
    s.add_argument("values", nargs="+", metavar="key=value")
    s.set_defaults(fn=cmd_set)

    s = sub.add_parser("brightness", help="set brightness (0-100)")
    s.add_argument("value", type=int, choices=range(0, 101), metavar="0-100")
    s.add_argument("monitor", nargs="?", default="all")
    s.set_defaults(fn=cmd_brightness)

    s = sub.add_parser("range", help="brightness matching: the range each monitor gets for 'all'")
    s.add_argument("key", nargs="?", help="monitor key (see: monctl list)")
    s.add_argument("low", nargs="?", help="0-100, or 'reset'")
    s.add_argument("high", nargs="?")
    s.set_defaults(fn=cmd_range, no_discover=True)

    s = sub.add_parser("schedule", help="time-of-day profiles: list|add HH:MM PROFILE|remove HH:MM")
    s.add_argument("action", nargs="?", default="list", choices=["list", "add", "remove"])
    s.add_argument("args", nargs="*")
    s.set_defaults(fn=cmd_schedule, no_discover=True)

    s = sub.add_parser("profile", help="list/show/save/apply/delete profiles")
    s.add_argument("action", choices=["list", "show", "save", "apply", "delete"])
    s.add_argument("name", nargs="?")
    s.set_defaults(fn=cmd_profile)

    s = sub.add_parser("auto", help="automatic profiles: list|on|off|default|add|remove|procs")
    s.add_argument("action", nargs="?", default="list",
                   choices=["list", "on", "off", "default", "add", "remove", "procs"])
    s.add_argument("args", nargs="*")
    s.add_argument("--focused", action="store_true",
                   help="with add: only while the app's window has focus (KDE Plasma, tray only)")
    s.set_defaults(fn=cmd_auto, no_discover=True)

    s = sub.add_parser("watch", help="apply automatic profiles without the tray (Ctrl+C to stop)")
    s.add_argument("--interval", type=float, default=3.0)
    s.set_defaults(fn=cmd_watch, no_discover=True)

    s = sub.add_parser("config", help="show or change monctl settings")
    s.add_argument("key", nargs="?", choices=["msigd"])
    s.add_argument("value", nargs="?")
    s.set_defaults(fn=cmd_config, no_discover=True)

    s = sub.add_parser("tray", help="run the tray icon")
    s.add_argument("--window", action="store_true", help="also open the window")
    s.set_defaults(fn=cmd_tray, no_discover=True)
    return p


def main(argv: list[str] | None = None) -> int:
    p = build_parser()
    a = p.parse_args(argv)
    if not getattr(a, "fn", None):
        p.print_help()
        return 0
    try:
        offline = getattr(a, "no_discover", False) or (
            a.cmd == "profile" and a.action in ("list", "show", "delete"))
        return a.fn(a, [] if offline else discover())
    except runner.ToolError as e:
        return _err(str(e))
