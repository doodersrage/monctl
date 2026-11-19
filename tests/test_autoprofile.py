import os

import pytest

from monctl import autoprofile as ap


def mkproc(root, pid, comm, argv, env=None):
    d = root / str(pid)
    d.mkdir()
    (d / "comm").write_text(comm + "\n")
    (d / "cmdline").write_bytes(b"\0".join(a.encode() for a in argv) + b"\0")
    (d / "environ").write_bytes(b"\0".join(f"{k}={v}".encode() for k, v in (env or {}).items()))


@pytest.fixture
def proc(tmp_path):
    root = tmp_path / "proc"
    root.mkdir()
    (root / "self").mkdir()                      # non-numeric entries are ignored
    mkproc(root, 10, "steam", ["/home/u/.steam/steam"], {"SteamAppId": "0"})
    mkproc(root, 11, "steamwebhelper", ["steamwebhelper"], {"SteamAppId": "730"})
    mkproc(root, 12, "electron", ["/opt/App/app.asar --enable-sandbox --lang=en"])
    return root


def names(root):
    return {p.pid: p for p in ap.Scanner(root).scan()}


def test_names_and_steam_client_not_a_game(proc):
    ps = names(proc)
    assert ps[10].names == {"steam"} and not ps[10].steam_game
    assert not ps[11].steam_game                  # client helper, even with an app id
    assert ps[12].names == {"electron", "app.asar"}


def test_proton_game_matches_by_exe_and_steam(proc):
    mkproc(proc, 20, "Cyberpunk2077.e",
           ["Z:\\\\games\\\\Cyberpunk 2077\\\\bin\\\\Cyberpunk2077.exe", "-fullscreen"],
           {"SteamAppId": "1091500"})
    ps = ap.Scanner(proc).scan()
    assert ap.rule_matches("cyberpunk2077", ps)
    assert ap.rule_matches("Cyberpunk2077.exe", ps)
    assert ap.rule_matches(ap.STEAM_GAME, ps)
    assert not ap.rule_matches("blender", ps)


def test_pick_first_rule_wins(proc):
    mkproc(proc, 30, "blender", ["/usr/bin/blender"])
    ps = ap.Scanner(proc).scan()
    rules = [{"match": ap.STEAM_GAME, "profile": "Gaming"}, {"match": "blender", "profile": "Work"},
             {"match": "electron", "profile": "Other"}]
    assert ap.pick(rules, ps) == "Work"
    mkproc(proc, 31, "game", ["/g/game"], {"SteamGameId": "42"})
    assert ap.pick(rules, ap.Scanner(proc).scan()) == "Gaming"


def test_watcher_transitions(proc):
    applied = []
    w = ap.Watcher(applied.append, ap.Scanner(proc))
    cfg = {"auto_enabled": True, "auto_default": "Desktop",
           "auto_rules": [{"match": "blender", "profile": "Work"}]}
    assert w.tick(cfg) is None                    # nothing running: leave manual choice alone
    mkproc(proc, 40, "blender", ["/usr/bin/blender"])
    assert w.tick(cfg) == "Work"
    assert w.tick(cfg) is None                    # still running: no re-apply
    import shutil
    shutil.rmtree(proc / "40")
    assert w.tick(cfg) == "Desktop"               # exited: back to default
    assert w.tick(cfg) is None
    assert applied == ["Work", "Desktop"]


def test_watcher_disabled_and_no_default(proc):
    applied = []
    w = ap.Watcher(applied.append, ap.Scanner(proc))
    mkproc(proc, 50, "blender", ["/usr/bin/blender"])
    rules = [{"match": "blender", "profile": "Work"}]
    assert w.tick({"auto_enabled": False, "auto_rules": rules}) is None
    assert w.tick({"auto_enabled": True, "auto_rules": rules, "auto_default": ""}) == "Work"
    import shutil
    shutil.rmtree(proc / "50")
    assert w.tick({"auto_enabled": True, "auto_rules": rules, "auto_default": ""}) is None
    assert applied == ["Work"]


def test_scanner_only_own_processes(proc, monkeypatch):
    s = ap.Scanner(proc)
    s.uid = os.getuid() + 1                       # pretend every entry belongs to someone else
    assert s.scan() == []


def test_cli_auto_rules(tmp_path, monkeypatch, capsys):
    from monctl import cli, profiles
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    profiles._save({"Gaming": {}, "Desktop": {}})
    assert cli.main(["auto", "add", "steam:game", "Gaming"]) == 0
    assert cli.main(["auto", "add", "blender", "Nope"]) == 1
    assert cli.main(["auto", "default", "Desktop"]) == 0
    assert cli.main(["auto", "on"]) == 0
    out = capsys.readouterr().out
    assert "automatic profiles: on   default: Desktop" in out and "steam:game" in out
    assert cli.main(["auto", "remove", "steam:game"]) == 0
    assert cli.main(["auto", "remove", "steam:game"]) == 1


def test_reaper_launch_counts_as_steam_game(proc):
    mkproc(proc, 60, "srt-bwrap", ["srt-bwrap"], {"SteamAppId": "7"})   # client's own container
    assert ap.pick([{"match": ap.STEAM_GAME, "profile": "G"}], ap.Scanner(proc).scan()) is None
    mkproc(proc, 61, "reaper", ["/s/ubuntu12_32/reaper", "SteamLaunch", "AppId=570", "--", "/g/dota2"])
    ps = names(proc)
    assert ps[61].steam_game and ps[61].steam_app == "570"
