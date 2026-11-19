import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_install_files_installs_and_uninstalls(tmp_path):
    subprocess.run([str(ROOT / "install-files.sh"), str(tmp_path)], check=True)
    for f in ["usr/share/applications/monctl.desktop",
              "usr/share/metainfo/io.github.doodersrage.monctl.metainfo.xml",
              "usr/share/bash-completion/completions/monctl", "usr/share/zsh/site-functions/_monctl",
              "usr/share/fish/vendor_completions.d/monctl.fish", "usr/share/man/man1/monctl.1",
              "usr/share/licenses/monctl/LICENSE"]:
        assert (tmp_path / f).is_file(), f
    subprocess.run([str(ROOT / "install-files.sh"), "--uninstall", str(tmp_path)], check=True)
    assert not any(p.is_file() for p in tmp_path.rglob("*"))


def test_versions_agree():
    from monctl import __version__
    assert f'<release version="{__version__}"' in (ROOT / "data/io.github.doodersrage.monctl.metainfo.xml").read_text()
    assert f"## {__version__}\n" in (ROOT / "CHANGELOG.md").read_text()
    assert (ROOT / "debian/changelog").read_text().startswith(f"monctl ({__version__})")
    assert f".TH MONCTL 1" in (ROOT / "docs/monctl.1").read_text()


def test_complete_names(tmp_path, monkeypatch, capsys):
    from monctl import cli, profiles
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    profiles._save({"Gaming": {"MAG323UPF": {}}, "Night": {"U28E590": {}}})
    assert cli.main(["_complete", "profiles"]) == 0
    assert capsys.readouterr().out.split() == ["Gaming", "Night"]
    cli.main(["_complete", "monitors"])
    assert capsys.readouterr().out.split() == ["all", "MAG323UPF", "U28E590"]
    cli.main(["_complete", "settings"])
    assert "game_mode" in capsys.readouterr().out.split()
