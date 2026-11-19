from monctl import autoprofile as ap
from monctl import steam


def acf(appid, name):
    return f'"AppState"\n{{\n\t"appid"\t\t"{appid}"\n\t"name"\t\t"{name}"\n\t"installdir"\t\t"x"\n}}\n'


def make_steam(tmp_path):
    root = tmp_path / "Steam"
    lib1 = root / "steamapps"
    lib2 = tmp_path / "Games" / "SteamLibrary" / "steamapps"
    lib1.mkdir(parents=True)
    lib2.mkdir(parents=True)
    (lib1 / "libraryfolders.vdf").write_text(
        f'"libraryfolders"\n{{\n\t"0"\n\t{{\n\t\t"path"\t\t"{root}"\n\t}}\n'
        f'\t"1"\n\t{{\n\t\t"path"\t\t"{lib2.parent}"\n\t}}\n}}\n')
    (lib1 / "appmanifest_646570.acf").write_text(acf(646570, "Slay the Spire"))
    (lib1 / "appmanifest_1493710.acf").write_text(acf(1493710, "Proton Experimental"))
    (lib1 / "appmanifest_1070560.acf").write_text(acf(1070560, "Steam Linux Runtime 1.0 (scout)"))
    (lib2 / "appmanifest_1086940.acf").write_text(acf(1086940, "Baldur's Gate 3"))
    (lib2 / "appmanifest_bad.acf").write_text("garbage")
    return root


def test_installed_games_across_libraries_without_tools(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "nohome"))
    monkeypatch.setenv("MONCTL_STEAM_ROOT", str(make_steam(tmp_path)))
    assert steam.installed_games() == {"1086940": "Baldur's Gate 3", "646570": "Slay the Spire"}


def test_no_steam(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("MONCTL_STEAM_ROOT", raising=False)
    assert steam.installed_games() == {}


def test_app_id():
    assert steam.app_id("steam:646570") == "646570"
    assert steam.app_id(ap.STEAM_GAME) is None and steam.app_id("blender") is None


def test_rule_for_one_steam_game():
    procs = [ap.Proc(1, {"steam"}, "646570"),               # client with an app id: not a game
             ap.Proc(2, {"slaythespire"}, "646570")]
    assert ap.rule_matches("steam:646570", procs)
    assert not ap.rule_matches("steam:1086940", procs)
    assert not ap.rule_matches("steam:646570", procs[:1])
    rules = [{"match": "steam:1086940", "profile": "BG3"}, {"match": "steam:646570", "profile": "Cards"},
             {"match": ap.STEAM_GAME, "profile": "Game"}]
    assert ap.pick(rules, procs) == "Cards"


def test_cli_games(tmp_path, monkeypatch, capsys):
    from monctl import cli, profiles
    monkeypatch.setenv("HOME", str(tmp_path / "nohome"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("MONCTL_STEAM_ROOT", str(make_steam(tmp_path)))
    assert cli.main(["auto", "games"]) == 0
    assert "steam:646570     Slay the Spire" in capsys.readouterr().out
    profiles._save({"Cards": {}})
    assert cli.main(["auto", "add", "steam:646570", "Cards"]) == 0
    assert "steam:646570 (Slay the Spire)" in capsys.readouterr().out
