"""0.3.0: hotplug/resume detection, finishing skipped profile applies, shortcut actions."""

import time

import pytest

from monctl import hotplug, monitors, profiles, runner


# ------------------------------------------------------------------ hotplug

def mk_sys(root, connectors=None, hid=None):
    drm = root / "class" / "drm"
    for name, status in (connectors or {}).items():
        (drm / name).mkdir(parents=True, exist_ok=True)
        (drm / name / "status").write_text(status + "\n")
    for name, hid_id in (hid or {}).items():
        d = root / "class" / "hidraw" / name / "device"
        d.mkdir(parents=True, exist_ok=True)
        (d / "uevent").write_text(f"DRIVER=hid-generic\nHID_ID={hid_id}\nHID_NAME=x\n")


def test_hotplug_connector_and_msi_hid(tmp_path):
    mk_sys(tmp_path, {"card1-DP-1": "connected", "card1-DP-3": "connected"},
           {"hidraw4": "0003:00001462:00003FA4", "hidraw1": "0003:0000046D:0000C08B"})
    clock = [0.0]
    h = hotplug.Hotplug(tmp_path, clock=lambda: clock[0])
    assert h.tick() is None                                   # first tick only records
    assert h.snapshot()[1] == ("hidraw4",)                    # only the MSI vendor counts
    mk_sys(tmp_path, hid={"hidraw7": "0003:0000046D:0000C08C"})   # a mouse: ignored
    assert h.tick() is None
    mk_sys(tmp_path, {"card1-DP-3": "disconnected"})
    assert h.tick() == "monitors changed"
    assert h.tick() is None
    import shutil
    shutil.rmtree(tmp_path / "class" / "hidraw" / "hidraw4")
    assert h.tick() == "monitors changed"


def test_hotplug_resume_from_clock_jump(tmp_path):
    mk_sys(tmp_path, {"card1-DP-1": "connected"})
    clock = [10.0]
    h = hotplug.Hotplug(tmp_path, clock=lambda: clock[0])
    h.tick()
    clock[0] += 0.1                       # normal drift
    assert h.tick() is None
    clock[0] += 600                       # ten minutes asleep
    assert h.tick() == "resumed"
    assert h.tick() is None


def test_real_clock_offset_is_stable():
    h = hotplug.Hotplug()
    h.tick()
    assert h.tick() != "resumed"


# ----------------------------------------------------- profiles: only/skipped

class FakeMon(monitors.Monitor):
    def __init__(self, key, fail=False, **st):
        super().__init__(key=key, label=key, bus=1)
        self.st = {"brightness": 50, "contrast": 50, **st}
        self.fail = fail
        self.calls = []

    def state(self):
        return dict(self.st)

    def apply(self, values):
        if self.fail:
            raise runner.ToolError(f"{self.key}: no answer")
        self.calls.append(dict(values))
        self.st.update(values)


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    profiles._save({"Desk": {"A": {"brightness": 40}, "B": {"brightness": 41}},
                    "Game": {"A": {"brightness": 90}, "B": {"brightness": 91}}})
    return tmp_path


def test_profile_apply_reports_skipped_and_only(cfg):
    a, b = FakeMon("A"), FakeMon("B", fail=True)
    skipped = set()
    warns = profiles.apply("Desk", [a, b], skipped=skipped)
    assert skipped == {"B"} and len(warns) == 1
    skipped = set()
    profiles.apply("Desk", [a], skipped=skipped)
    assert skipped == {"B"}                                   # not connected
    a.calls.clear()
    b = FakeMon("B")
    profiles.apply("Desk", [a, b], only={"B"})
    assert a.calls == [] and b.calls == [{"brightness": 41}]


# ---------------------------------------------------------- tray controller

@pytest.fixture
def ctl(cfg, monkeypatch):
    pytest.importorskip("PyQt6")
    from PyQt6.QtWidgets import QApplication
    from monctl import qt
    app = QApplication.instance() or QApplication([])
    c = qt.Controller()
    c.app = app                     # keep the application alive (else queued signals are dropped)
    c.auto_timer.stop()
    c.notices = []
    c.errors = []
    c.notice.connect(c.notices.append)
    c.error.connect(c.errors.append)
    return c


def drain(c):
    from PyQt6.QtWidgets import QApplication
    deadline = time.monotonic() + 5
    while c._pending and time.monotonic() < deadline:
        c.pool.waitForDone(20)
        QApplication.processEvents()
    QApplication.processEvents()


def test_controller_finishes_skipped_monitor_when_it_returns(ctl, monkeypatch):
    from monctl import qt
    a = FakeMon("A")
    ctl.monitors = [a]
    ctl.apply_profile("Game")
    drain(ctl)
    assert a.st["brightness"] == 90
    assert ctl.unfinished == ("Game", {"B"})
    b = FakeMon("B")
    monkeypatch.setattr(qt, "discover", lambda: [a, b])      # B was switched on again
    a.calls.clear()
    ctl.refresh()
    drain(ctl)
    drain(ctl)
    assert b.calls == [{"brightness": 91}] and a.calls == []  # only the missing one is touched
    assert ctl.unfinished is None
    assert any("Applied Game to B" in n for n in ctl.notices)


def test_newer_profile_replaces_unfinished(ctl, monkeypatch):
    from monctl import qt
    a = FakeMon("A")
    ctl.monitors = [a]
    ctl.apply_profile("Game")
    drain(ctl)
    ctl.apply_profile("Desk")
    drain(ctl)
    assert ctl.unfinished == ("Desk", {"B"})
    b = FakeMon("B")
    monkeypatch.setattr(qt, "discover", lambda: [a, b])
    ctl.refresh()
    drain(ctl)
    drain(ctl)
    assert b.st["brightness"] == 41                           # Desk, not the older Game


def test_next_profile_and_index(ctl):
    a, b = FakeMon("A"), FakeMon("B")
    ctl.monitors = [a, b]
    ctl.next_profile()
    drain(ctl)
    assert ctl.current_profile == "Desk"
    ctl.next_profile()
    drain(ctl)
    assert ctl.current_profile == "Game" and a.st["brightness"] == 90
    ctl.next_profile()
    drain(ctl)
    assert ctl.current_profile == "Desk"                      # wraps around
    ctl.apply_profile_at(5)
    assert "No profile 6" in ctl.notices[-1]


def test_brightness_steps_share_one_level_and_coalesce(ctl):
    a, b = FakeMon("A", brightness=95), FakeMon("B", brightness="30")   # msigd reports strings
    ctl.monitors = [a, b]
    ctl.states = {"A": a.state(), "B": b.state()}
    assert ctl.level() == 62                                  # average of 95 and 30
    for _ in range(3):
        ctl.step_brightness(+10)                              # 62 -> 70 -> 80 -> 90 (snaps to grid)
    drain(ctl)
    assert a.st["brightness"] == 90 and b.st["brightness"] == 90
    assert len(a.calls) <= 2                                  # repeats share a write
    ctl.step_brightness(+10)
    ctl.step_brightness(+10)                                  # clamps at 100
    drain(ctl)
    assert a.st["brightness"] == 100 and ctl.states["B"]["brightness"] == 100


def test_brightness_level_uses_matching_ranges(ctl):
    from monctl import levels
    levels.set_range("B", 0, 80)
    a, b = FakeMon("A"), FakeMon("B")
    ctl.monitors = [a, b]
    ctl.states = {"A": a.state(), "B": b.state()}
    ctl.set_level(50)
    drain(ctl)
    assert a.st["brightness"] == 50 and b.st["brightness"] == 40
    a.calls.clear()
    ctl.set_level(50)
    drain(ctl)
    assert a.calls == []                                      # already there: no write


def test_toggle_auto(ctl):
    from monctl import settings
    ctl.toggle_auto()
    assert settings.get("auto_enabled") is True and ctl.notices[-1] == "Automatic profiles on"
    ctl.toggle_auto()
    assert settings.get("auto_enabled") is False


# ------------------------------------------------------------- shortcuts

def test_shortcut_ids_match_tray_actions():
    pytest.importorskip("PyQt6")
    from monctl import qt, shortcuts
    assert {sid for sid, _d, _t in shortcuts.SHORTCUTS} == set(qt.Tray.ACTIONS)


def test_shortcut_activation_filters_other_sessions():
    from monctl import shortcuts
    got = []
    s = shortcuts.PortalShortcuts(got.append, on_error=lambda m: None)
    s.session = "/org/freedesktop/portal/desktop/session/1_2/monctl1"
    s._activated("/org/freedesktop/portal/desktop/session/1_2/other", "profile-1", 0, {})
    s._activated(s.session, "profile-2", 0, {})
    assert got == ["profile-2"]
    bound = []
    s.on_bound = bound.append
    s._bound({"shortcuts": [("profile-1", {"trigger_description": "Meta+Alt+1"})]})
    assert bound == [{"profile-1": "Meta+Alt+1"}]


# --------------------------------------------------------- levels / schedule

def test_levels_mapping(cfg):
    from monctl import levels
    assert levels.to_monitor("X", 70) == 70                   # no range: unchanged
    levels.set_range("S", 10, 60)
    assert [levels.to_monitor("S", v) for v in (0, 50, 100, 150)] == [10, 35, 60, 60]
    assert levels.to_level("S", 35) == 50 and levels.to_level("S", 5) == 0
    assert levels.to_level("S", "bad") is None
    with pytest.raises(ValueError):
        levels.set_range("S", 60, 60)
    levels.set_range("S", None, None)
    assert levels.ranges() == {}


def test_schedule_current_and_crossed(cfg):
    import datetime as dt
    from monctl import schedule
    c = {"schedule": [{"at": "21:00", "profile": "Night"}, {"at": "07:30", "profile": "Day"},
                      {"at": "bad", "profile": "x"}]}
    d = dt.datetime(2026, 11, 19)
    assert schedule.current(d.replace(hour=12), c) == "Day"
    assert schedule.current(d.replace(hour=22), c) == "Night"
    assert schedule.current(d.replace(hour=3), c) == "Night"        # wraps from yesterday
    assert schedule.crossed(d.replace(hour=20, minute=59), d.replace(hour=21), c) == "Night"
    assert schedule.crossed(d.replace(hour=21), d.replace(hour=21, minute=3), c) is None
    # asleep from 20:00 until 08:00 next day: both passed, the latest (Day) wins
    assert schedule.crossed(d.replace(hour=20), d.replace(day=20, hour=8), c) == "Day"
    assert schedule.crossed(d.replace(hour=20), d.replace(day=25, hour=8), c) == "Day"


def test_scheduler_does_nothing_at_start(cfg):
    import datetime as dt
    from monctl import schedule
    now = [dt.datetime(2026, 11, 19, 21, 0, 30)]
    s = schedule.Scheduler(clock=lambda: now[0])
    c = {"schedule": [{"at": "21:00", "profile": "Night"}, {"at": "21:01", "profile": "Late"}]}
    assert s.tick(c) is None                                  # 21:00 passed before we started
    now[0] = now[0].replace(minute=1, second=2)
    assert s.tick(c) == "Late"


def test_watcher_returns_to_scheduled_slot(cfg, monkeypatch):
    from monctl import autoprofile
    monkeypatch.setattr(autoprofile.Watcher, "leave_profile", staticmethod(lambda c: "Night"))
    applied = []
    procs = [[autoprofile.Proc(1, {"game"})]]

    class S:
        def scan(self):
            return procs[0]
    w = autoprofile.Watcher(applied.append, S())
    c = {"auto_enabled": True, "auto_default": "Desk", "auto_rules": [{"match": "game", "profile": "Game"}]}
    w.tick(c)
    procs[0] = []
    w.tick(c)
    assert applied == ["Game", "Night"]


def test_cli_range_and_schedule(cfg, capsys):
    from monctl import cli
    assert cli.main(["range", "U28E590", "0", "80"]) == 0
    assert cli.main(["range", "U28E590", "90", "10"]) == 1
    assert cli.main(["schedule", "add", "21:00", "Desk"]) == 0
    assert cli.main(["schedule", "add", "25:00", "Desk"]) == 1
    assert cli.main(["schedule", "add", "07:00", "Nope"]) == 1
    out = capsys.readouterr().out
    assert "U28E590            0-80" in out and "21:00  -> Desk" in out
    assert cli.main(["schedule", "remove", "21:00"]) == 0
    assert cli.main(["range", "U28E590", "reset"]) == 0
