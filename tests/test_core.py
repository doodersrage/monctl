import json

import pytest

from monctl import ddc, monitors, msi, profiles, runner

DETECT = """\
Display 1
   I2C bus:          /dev/i2c-4
   DRM connector:    card1-DP-1
   Monitor:          VSC:VX3418-2KPC:WFJ223620413

Display 2
   I2C bus:          /dev/i2c-5
   DRM connector:    card1-DP-2
   Monitor:          SAM:U28E590:���

Invalid display
   I2C bus:          /dev/i2c-7
   DRM connector:    card1-HDMI-A-1

Display 3
   I2C bus:          /dev/i2c-6
   DRM connector:    card1-DP-3
   Monitor:          MSI:MSI MAG323UPF:
"""

QUERY = """\
Unexpected id combination <00x><V61>
game_mode : user
brightness : 70
smart_crosshair_color : red
serial : DC7T033800546
"""


class FakeRunner:
    def __init__(self, responses):
        self.responses, self.calls = responses, []

    def __call__(self, args, timeout=20):
        self.calls.append(args)
        for key, out in self.responses.items():
            if key in " ".join(args):
                return out
        return ""


@pytest.fixture
def fake(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    exe = tmp_path / "msigd"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    monkeypatch.setenv("MONCTL_MSIGD", str(exe))
    f = FakeRunner({"detect": DETECT, "--list": "1,SER,MS,MSI Gaming Controller,/dev/hidraw4\n",
                    "--query": QUERY, "getvcp": "VCP 10 C 55 100\nVCP 12 C 70 100\n"})
    monkeypatch.setattr(runner, "run", f)
    return f


def test_parse_detect_skips_invalid_and_binary_serials():
    ds = ddc.parse_detect(DETECT)
    assert [(d.bus, d.connector, d.mfg, d.model) for d in ds] == [
        (4, "DP-1", "VSC", "VX3418-2KPC"), (5, "DP-2", "SAM", "U28E590"),
        (6, "DP-3", "MSI", "MSI MAG323UPF")]
    assert ds[0].serial == "WFJ223620413" and ds[1].serial == ""


def test_parse_getvcp():
    assert ddc.parse_getvcp("VCP 10 C 100 100\nVCP 12 C 75 100\nVCP 60 SNC x0f\n") == \
        {"brightness": 100, "contrast": 75}


def test_parse_query_ignores_warnings():
    assert msi.parse_query(QUERY) == {"game_mode": "user", "brightness": "70",
                                      "smart_crosshair_color": "red", "serial": "DC7T033800546"}


@pytest.mark.parametrize("name,value", [("kvm", "type_c"), ("pip", "pip"), ("free_sync", "on"),
                                        ("zero_latency", "off")])
def test_refused(name, value):
    with pytest.raises(msi.MsiError, match="refusing"):
        msi.check(name, value)


@pytest.mark.parametrize("name,value", [("brightness", "101"), ("brightness", "-1"),
                                        ("brightness", "x"), ("game_mode", "turbo"),
                                        ("serial", "1"), ("smart_crosshair_color", "blue")])
def test_invalid(name, value):
    with pytest.raises(msi.MsiError):
        msi.check(name, value)


def test_check_normalises():
    assert msi.check("brightness", " 070 ") == "70"
    assert msi.check("game_mode", "FPS") == "fps"
    assert msi.check("kvm", "upstream") == "upstream"


def test_apply_validates_everything_first(fake):
    with pytest.raises(msi.MsiError):
        msi.apply({"brightness": 50, "kvm": "type_c"})
    assert not [c for c in fake.calls if "--brightness" in c]


def test_apply_sends_game_mode_first(fake):
    msi.apply({"brightness": 50, "game_mode": "fps", "eye_saver": "on"})
    sets = [c for c in fake.calls if "--query" not in c and "--list" not in c]
    assert sets[0][-2:] == ["--game_mode", "fps"]
    assert sets[1][-4:] == ["--brightness", "50", "--eye_saver", "on"]


def test_discover_assigns_msigd_to_msi(fake):
    mons = monitors.discover()
    assert [(m.key, m.backend) for m in mons] == [
        ("VX3418-2KPC", "ddc"), ("U28E590", "ddc"), ("MAG323UPF", "msigd")]
    assert monitors.find(mons, "dp-3")[0].key == "MAG323UPF"
    assert monitors.find(mons, "2")[0].key == "U28E590"
    assert len(monitors.find(mons, "all")) == 3


def test_ddc_rejects_msi_only_settings(fake):
    mon = monitors.discover()[0]
    with pytest.raises(runner.ToolError, match="not supported over DDC"):
        mon.apply({"game_mode": "fps"})


def test_profile_roundtrip(fake):
    mons = monitors.discover()
    prof = profiles.save("Night", mons)
    assert prof["VX3418-2KPC"] == {"brightness": 55, "contrast": 70}
    assert prof["MAG323UPF"] == {"game_mode": "user", "brightness": "70",
                                 "smart_crosshair_color": "red"}
    assert json.loads(profiles.path().read_text())["Night"] == prof

    fake.calls.clear()
    warns = profiles.apply("Night", mons[1:])          # VX3418 "unplugged"
    assert warns == ["VX3418-2KPC: not connected, skipped"]
    assert any("setvcp" in c for c in fake.calls)
    assert any("--game_mode" in c for c in fake.calls)
    assert profiles.delete("Night") and not profiles.delete("Night")
