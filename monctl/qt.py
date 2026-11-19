"""PyQt6 tray icon and settings window.

All monitor I/O runs on one background thread, one job at a time, so msigd and
ddcutil never talk to the hardware concurrently and the UI never blocks.
"""

from __future__ import annotations

import os
import shutil
import sys
import traceback
from pathlib import Path

from PyQt6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QActionGroup, QIcon
from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                             QFormLayout, QGroupBox, QHBoxLayout, QInputDialog, QLabel,
                             QListWidget, QListWidgetItem, QMenu, QMessageBox, QPushButton,
                             QSlider, QSpinBox, QSystemTrayIcon, QTimeEdit, QVBoxLayout, QWidget)

from . import __version__, autoprofile, focus, hotplug, levels, msi, profiles, runner, schedule, settings, shortcuts
from .monitors import Monitor, discover

MSI_CHOICES = ("game_mode", "night_vision", "smart_crosshair_icon", "smart_crosshair_color",
               "response_time", "eye_saver")
LABELS = {
    "game_mode": "Game mode", "night_vision": "Night Vision", "smart_crosshair_icon": "Crosshair",
    "smart_crosshair_color": "Crosshair color", "response_time": "Response time",
    "eye_saver": "Eye Saver", "brightness": "Brightness", "contrast": "Contrast",
}


AUTOSTART_NAME = "monctl-tray.desktop"


def autostart_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(base) / "autostart" / AUTOSTART_NAME


def autostart_entry() -> str:
    exe = shutil.which("monctl") or f"{sys.executable} -m monctl"
    return ("[Desktop Entry]\nType=Application\nName=monctl\n"
            "Comment=Monitor profiles and brightness in the system tray\n"
            f"Exec={exe} tray\nIcon=video-display\nX-GNOME-Autostart-enabled=true\n")


def set_autostart(on: bool) -> None:
    p = autostart_path()
    if on:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(autostart_entry())
    else:
        p.unlink(missing_ok=True)


INPUT_LABELS = {"dp": "DisplayPort", "dp1": "DisplayPort 1", "dp2": "DisplayPort 2", "hdmi1": "HDMI 1",
                "hdmi2": "HDMI 2", "usbc": "USB-C", "vga1": "VGA", "vga2": "VGA 2", "dvi1": "DVI",
                "dvi2": "DVI 2"}


def confirm_input(parent, m: Monitor, value: str) -> bool:
    return QMessageBox.question(
        parent, "Switch input",
        f"Switch {m.label} to {INPUT_LABELS.get(value, value)}?\n\n"
        "This screen will show that input instead of this PC. Switch back with the "
        "monitor's buttons or with monctl.") == QMessageBox.StandardButton.Yes


def nice(s: str) -> str:
    return s.replace("_", " ").replace("icon", "icon ").capitalize().strip()


class _Signals(QObject):
    done = pyqtSignal(object)
    failed = pyqtSignal(str)


class _Job(QRunnable):
    def __init__(self, fn, done=None, failed=None):
        super().__init__()
        self.fn, self.sig = fn, _Signals()
        if done:
            self.sig.done.connect(done)
        if failed:
            self.sig.failed.connect(failed)

    def run(self):
        try:
            res = self.fn()
        except runner.ToolError as e:
            self.sig.failed.emit(str(e))
        except Exception:  # noqa: BLE001 - surface unexpected errors instead of dying silently
            self.sig.failed.emit(traceback.format_exc(limit=3))
        else:
            self.sig.done.emit(res)


class Controller(QObject):
    """Owns the monitor list and the single hardware worker thread."""

    monitors_changed = pyqtSignal(list)
    state_changed = pyqtSignal(str, dict)     # monitor key, state
    error = pyqtSignal(str)
    busy = pyqtSignal(bool)
    auto_switched = pyqtSignal(str)           # profile applied by an automatic rule
    profiles_changed = pyqtSignal()
    notice = pyqtSignal(str)                  # short informational message
    levels_changed = pyqtSignal()             # brightness matching ranges edited

    HOTPLUG_SETTLE_MS = 4000                  # monitors answer DDC/USB a few seconds after waking

    def __init__(self):
        super().__init__()
        self.pool = QThreadPool()
        self.pool.setMaxThreadCount(1)
        self.monitors: list[Monitor] = []
        self.states: dict[str, dict] = {}
        self.inputs: dict[str, list[str]] = {}               # selectable inputs per monitor
        self._jobs: set[_Job] = set()
        self._pending = 0
        self.current_profile: str | None = None
        self.unfinished: tuple[str, set[str]] | None = None   # profile + monitors it skipped
        self._bright: dict[str, int] = {}                     # brightness targets for key repeats
        self._bright_queued = False
        self._level: int | None = None                        # last "all monitors" level set
        self.watcher = autoprofile.Watcher(self._auto_apply)
        self._focus_failed = False
        self.scheduler = schedule.Scheduler()
        self.hotplug = hotplug.Hotplug()
        self.settle = QTimer(self, singleShot=True, interval=self.HOTPLUG_SETTLE_MS)
        self.settle.timeout.connect(self.refresh)
        self.auto_timer = QTimer(self, interval=3000)
        self.auto_timer.timeout.connect(self._tick)
        self.auto_timer.start()

    def _tick(self):
        try:
            if self.hotplug.tick():
                self.settle.start()    # (re)start: wait until things stop changing
        except Exception as e:  # noqa: BLE001 - keep the timer alive
            self.error.emit(f"Monitor detection: {e}")
        if not self.monitors:      # wait for the first discovery
            return
        self._auto_tick()
        try:
            due = self.scheduler.tick()
            # while a game rule is active the game's profile wins; the schedule's current slot
            # is applied when it exits (Watcher.leave_profile)
            if due and self.watcher.active is None:
                if due in profiles.load():
                    self.apply_profile(due, on_done=lambda n: self.notice.emit(f"Scheduled: {n}"))
                else:
                    self.error.emit(f"Schedule: no profile named {due!r}")
        except Exception as e:  # noqa: BLE001 - keep the timer alive
            self.error.emit(f"Schedule: {e}")

    def _auto_tick(self):
        try:
            cfg = settings.load()
            self._ensure_focus(autoprofile.needs_focus(cfg))
            self.watcher.tick(cfg)
        except Exception as e:  # noqa: BLE001 - keep the timer alive
            self.error.emit(f"Automatic profiles: {e}")

    def _ensure_focus(self, wanted: bool):
        """Run the KWin focus tracker only while a rule needs it."""
        tracker = self.watcher.focus
        if wanted and tracker is None and not self._focus_failed:
            reason = focus.unavailable_reason()
            if reason:
                self._focus_failed = True
                self.error.emit(f"\"Only while focused\" rules {reason}; treating them as \"while running\"")
                return
            tracker = focus.FocusTracker(
                on_change=lambda _pid: self.monitors and QTimer.singleShot(0, self._auto_tick))
            try:
                tracker.start()
            except Exception as e:  # noqa: BLE001 - D-Bus/KWin refusal: fall back to running
                self._focus_failed = True
                tracker.stop()
                self.error.emit(f"Focus tracking unavailable ({e}); treating focus rules as \"while running\"")
                return
            self.watcher.focus = tracker
        elif not wanted and tracker is not None:
            tracker.stop()
            self.watcher.focus = None

    def shutdown(self):
        if self.watcher.focus is not None:
            self.watcher.focus.stop()
            self.watcher.focus = None

    def _auto_apply(self, name: str):
        if name not in profiles.load():
            self.error.emit(f"Automatic profiles: no profile named {name!r}")
            return
        self.apply_profile(name, on_done=self.auto_switched.emit)

    def _submit(self, fn, done=None):
        self._pending += 1
        self.busy.emit(True)
        job = _Job(fn)
        self._jobs.add(job)

        def finish():
            self._jobs.discard(job)
            self._pending -= 1
            if not self._pending:
                self.busy.emit(False)

        job.sig.done.connect(lambda r: (done(r) if done else None, finish()))
        job.sig.failed.connect(lambda m: (self.error.emit(m), finish()))
        job.setAutoDelete(False)
        self.pool.start(job)

    def refresh(self):
        def work():
            mons = discover()
            ins = {}
            for m in mons:
                try:
                    ins[m.key] = m.inputs
                except runner.ToolError:
                    ins[m.key] = []
            return mons, {m.key: m.state() for m in mons}, ins

        def done(res):
            self.monitors, self.states, self.inputs = res
            self._bright.clear()
            self._level = None
            self.monitors_changed.emit(self.monitors)
            for k, st in self.states.items():
                self.state_changed.emit(k, st)
            self._finish_unfinished()
        self._submit(work, done)

    def _finish_unfinished(self):
        """A profile skipped some monitors (off/unplugged); apply it to them now that they're back."""
        if not self.unfinished:
            return
        name, keys = self.unfinished
        back = {m.key for m in self.monitors} & keys
        if back and name in profiles.load():
            self.apply_profile(name, only=back, on_done=lambda n: self.notice.emit(
                f"Applied {n} to {', '.join(sorted(back))}"))

    def monitor(self, key: str) -> Monitor | None:
        return next((m for m in self.monitors if m.key == key), None)

    def reload_state(self, m: Monitor):
        def done(st):
            self.states[m.key] = st
            self.state_changed.emit(m.key, st)
        self._submit(m.state, done)

    def apply(self, m: Monitor, values: dict):
        def work():
            m.apply(values)
            return m.state()

        def done(st):
            self.states[m.key] = st
            self.state_changed.emit(m.key, st)
        self._submit(work, done)

    def apply_profile(self, name: str, on_done=None, only: set[str] | None = None):
        mons = list(self.monitors)
        if only is None:
            self.current_profile = name
            self.unfinished = None

        def work():
            skipped: set[str] = set()
            warns = profiles.apply(name, mons, only=only, skipped=skipped)
            touched = [m for m in mons if only is None or m.key in only]
            return warns, skipped, {m.key: m.state() for m in touched if m.key not in skipped}

        def done(res):
            warns, skipped, states = res
            if self.current_profile == name:      # not replaced by a newer apply meanwhile
                self.unfinished = (name, skipped) if skipped else None
            self.states.update(states)
            self._bright.clear()
            self._level = None
            for k, st in states.items():
                self.state_changed.emit(k, st)
            if warns:
                self.error.emit("\n".join(warns))
            if on_done:
                on_done(name)
        self._submit(work, done)

    # -- shortcut actions -------------------------------------------------
    def apply_profile_at(self, index: int):
        names = list(profiles.load())
        if index >= len(names):
            self.notice.emit(f"No profile {index + 1} (there are {len(names)})")
            return
        self.apply_profile(names[index], on_done=lambda n: self.notice.emit(f"Applied {n}"))

    def next_profile(self):
        names = list(profiles.load())
        if not names:
            self.notice.emit("No profiles yet")
            return
        i = names.index(self.current_profile) + 1 if self.current_profile in names else 0
        self.apply_profile_at(i % len(names))

    def level(self) -> int | None:
        """The current "all monitors" brightness level (average over monitors, after matching)."""
        vals = [levels.to_level(m.key, self.states.get(m.key, {}).get("brightness")) for m in self.monitors]
        vals = [v for v in vals if v is not None]
        return round(sum(vals) / len(vals)) if vals else None

    def step_brightness(self, delta: int):
        cur = self._level if self._level is not None else self.level()
        if cur is None:
            return
        # snap to the step grid so +10 from 47 gives 50, not 57
        new = (cur // abs(delta) + (1 if delta > 0 else 0)) * abs(delta) if cur % abs(delta) else cur + delta
        self.set_level(max(0, min(100, new)))

    def set_level(self, level: int, quiet: bool = False):
        """Set every monitor to the "all monitors" level; rapid calls coalesce into one write."""
        self._level = level
        rng = levels.ranges()
        for m in self.monitors:
            self._bright[m.key] = levels.to_monitor(m.key, level, rng)
        if not self._bright:
            return
        if not quiet:
            self.notice.emit(f"Brightness {level}%")
        if self._bright_queued:
            return
        self._bright_queued = True
        mons = list(self.monitors)

        def work():
            self._bright_queued = False          # later presses queue a new write
            targets = dict(self._bright)
            for m in mons:
                if m.key in targets and str(self.states.get(m.key, {}).get("brightness")) != str(targets[m.key]):
                    m.apply({"brightness": targets[m.key]})
            return {m.key: targets[m.key] for m in mons if m.key in targets}

        def done(applied):
            for k, v in applied.items():
                self.states.setdefault(k, {})["brightness"] = v
                self.state_changed.emit(k, self.states[k])
        self._submit(work, done)

    def toggle_auto(self):
        on = not settings.get("auto_enabled")
        settings.set(auto_enabled=on)
        self.profiles_changed.emit()
        self.notice.emit(f"Automatic profiles {'on' if on else 'off'}")

    def save_profile(self, name: str, on_done=None):
        mons = list(self.monitors)
        def done(_r):
            self.profiles_changed.emit()
            if on_done:
                on_done(name)
        self._submit(lambda: profiles.save(name, mons), done)


# ----------------------------------------------------------------- window

class MonitorBox(QGroupBox):
    def __init__(self, ctl: Controller, m: Monitor):
        super().__init__(f"{m.label}  ·  {'USB (msigd)' if m.msi else 'DDC/CI'}")
        self.ctl, self.m = ctl, m
        self.updating = False
        form = QFormLayout(self)
        self.sliders: dict[str, tuple[QSlider, QLabel]] = {}
        for key in ("brightness", "contrast"):
            s = QSlider(Qt.Orientation.Horizontal)
            s.setRange(0, 100)
            val = QLabel("–")
            val.setMinimumWidth(30)
            s.valueChanged.connect(lambda v, lab=val: lab.setText(str(v)))
            s.sliderReleased.connect(lambda k=key, sl=s: self._send({k: sl.value()}))
            s.setPageStep(10)
            s.actionTriggered.connect(lambda _a, k=key, sl=s: QTimer.singleShot(
                0, lambda: None if sl.isSliderDown() else self._debounce(k, sl)))
            row = QHBoxLayout()
            row.addWidget(s)
            row.addWidget(val)
            form.addRow(LABELS[key], row)
            self.sliders[key] = (s, val)
        lo, hi = levels._range(m.key, None)
        self.lo, self.hi = QSpinBox(), QSpinBox()
        for sb, v in ((self.lo, lo), (self.hi, hi)):
            sb.setRange(0, 100)
            sb.setValue(v)
            sb.setSuffix("%")
            sb.editingFinished.connect(self._save_range)
        row = QHBoxLayout()
        row.addWidget(self.lo)
        row.addWidget(QLabel("to"))
        row.addWidget(self.hi)
        row.addStretch()
        rlab = QLabel("All-monitor range")
        rlab.setToolTip("Brightness this monitor gets when \"All monitors\" is at 0% and 100%.\n"
                        "Narrow it on monitors that look brighter than the others.")
        form.addRow(rlab, row)
        self.combos: dict[str, QComboBox] = {}
        ins = ctl.inputs.get(m.key) or []
        if ins:
            c = QComboBox()
            c.addItem("(unknown)", "")
            for v in ins:
                c.addItem(INPUT_LABELS.get(v, v), v)
            c.activated.connect(lambda _i, cb=c: self._switch_input(cb))
            form.addRow("Input", c)
            self.combos["input"] = c
        if m.msi:
            for key in MSI_CHOICES:
                c = QComboBox()
                for v in msi.WRITABLE[key]:
                    c.addItem(nice(v), v)
                c.activated.connect(lambda _i, k=key, cb=c: self._send({k: cb.currentData()}))
                form.addRow(LABELS[key], c)
                self.combos[key] = c
        self._timer = QTimer(self, singleShot=True, interval=400)
        self._timer.timeout.connect(self._flush)
        self._queued: dict = {}
        self.setEnabled(False)

    def _switch_input(self, cb: QComboBox):
        v = cb.currentData()
        cur = self.ctl.states.get(self.m.key, {}).get("input")
        if v and v != cur and confirm_input(self, self.m, v):
            self._send({"input": v})
        else:
            self.show_state(self.ctl.states.get(self.m.key, {}))   # undo the combo change

    def _save_range(self):
        lo, hi = self.lo.value(), self.hi.value()
        if lo >= hi:
            self.ctl.error.emit("Range: the low end must be below the high end")
            return
        levels.set_range(self.m.key, None, None) if (lo, hi) == (0, 100) else levels.set_range(self.m.key, lo, hi)
        self.ctl.levels_changed.emit()

    def _debounce(self, key, slider):
        self._queued[key] = slider.value()
        self._timer.start()

    def _flush(self):
        if self._queued:
            vals, self._queued = self._queued, {}
            self._send(vals)

    def _send(self, values: dict):
        if not self.updating:
            self.ctl.apply(self.m, values)

    def show_state(self, st: dict):
        self.updating = True
        try:
            for key, (s, lab) in self.sliders.items():
                if key in st and not s.isSliderDown():
                    s.setValue(int(st[key]))
                    lab.setText(str(int(st[key])))
            for key, c in self.combos.items():
                i = c.findData(st.get(key, "" if key == "input" else None))
                if i >= 0:
                    c.setCurrentIndex(i)
            self.setEnabled(True)
        finally:
            self.updating = False


class RuleDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add automatic profile")
        form = QFormLayout(self)
        self.app = QComboBox(editable=True)
        self.app.addItem("Any Steam game", autoprofile.STEAM_GAME)
        for n in autoprofile.running_names(autoprofile.Scanner().scan()):
            self.app.addItem(n, n)
        self.app.setToolTip("A running app, or type a process name (.exe optional for Proton games)")
        self.prof = QComboBox()
        self.prof.addItems(list(profiles.load()))
        self.focused = QCheckBox("Only while its window is focused")
        self.focused.setToolTip("Switch back when you Alt+Tab away from it (KDE Plasma)")
        form.addRow("When this runs:", self.app)
        form.addRow("", self.focused)
        form.addRow("Use profile:", self.prof)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    def rule(self) -> dict | None:
        i = self.app.currentIndex()
        text = self.app.currentText().strip()
        match = self.app.itemData(i) if i >= 0 and self.app.itemText(i) == text else text
        if not match or not self.prof.currentText():
            return None
        r = {"match": match, "profile": self.prof.currentText()}
        if self.focused.isChecked():
            r["focused"] = True
        return r


def rule_text(r: dict) -> str:
    what = "Any Steam game" if r["match"] == autoprofile.STEAM_GAME else r["match"]
    return f"{what}{' (focused)' if r.get('focused') else ''}  →  {r['profile']}"


class AutoBox(QGroupBox):
    def __init__(self, ctl: Controller):
        super().__init__("Automatic profiles")
        self.ctl = ctl
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.enabled = QCheckBox("Switch profiles while these apps run")
        self.enabled.toggled.connect(lambda on: settings.set(auto_enabled=on))
        top.addWidget(self.enabled)
        top.addStretch()
        top.addWidget(QLabel("Afterwards:"))
        self.default = QComboBox()
        self.default.setToolTip("Profile applied when the last matching app exits\n"
                                "(if a Schedule is set, its current profile is used instead)")
        self.default.activated.connect(lambda _i: settings.set(auto_default=self.default.currentData()))
        top.addWidget(self.default)
        lay.addLayout(top)
        self.list = QListWidget()
        self.list.setMaximumHeight(90)
        lay.addWidget(self.list)
        row = QHBoxLayout()
        b_add, b_del = QPushButton("Add…"), QPushButton("Remove")
        b_add.clicked.connect(self._add)
        b_del.clicked.connect(self._remove)
        row.addWidget(b_add)
        row.addWidget(b_del)
        row.addStretch()
        lay.addLayout(row)
        ctl.profiles_changed.connect(self.reload)
        self.reload()

    def reload(self):
        cfg = settings.load()
        self.enabled.blockSignals(True)
        self.enabled.setChecked(bool(cfg["auto_enabled"]))
        self.enabled.blockSignals(False)
        self.default.clear()
        self.default.addItem("(keep current)", "")
        for n in profiles.load():
            self.default.addItem(n, n)
        self.default.setCurrentIndex(max(0, self.default.findData(cfg["auto_default"])))
        self.list.clear()
        for r in cfg["auto_rules"]:
            it = QListWidgetItem(rule_text(r))
            it.setData(Qt.ItemDataRole.UserRole, r["match"])
            self.list.addItem(it)

    def _add(self):
        if not profiles.load():
            QMessageBox.information(self, "Automatic profiles", "Save a profile first.")
            return
        d = RuleDialog(self)
        if d.exec() and (r := d.rule()):
            rules = [x for x in settings.get("auto_rules") if x.get("match") != r["match"]]
            settings.set(auto_rules=rules + [r])
            self.reload()

    def _remove(self):
        it = self.list.currentItem()
        if it:
            match = it.data(Qt.ItemDataRole.UserRole)
            settings.set(auto_rules=[x for x in settings.get("auto_rules") if x.get("match") != match])
            self.reload()


class ScheduleBox(QGroupBox):
    def __init__(self, ctl: Controller):
        super().__init__("Schedule")
        self.ctl = ctl
        self.setToolTip("Apply a profile at a time of day. After a game, automatic profiles\n"
                        "return to the profile scheduled for that time.")
        lay = QVBoxLayout(self)
        self.list = QListWidget()
        self.list.setMaximumHeight(80)
        lay.addWidget(self.list)
        row = QHBoxLayout()
        self.at = QTimeEdit()
        self.at.setDisplayFormat("HH:mm")
        self.prof = QComboBox()
        b_add, b_del = QPushButton("Add"), QPushButton("Remove")
        b_add.clicked.connect(self._add)
        b_del.clicked.connect(self._remove)
        for w in (QLabel("At"), self.at, self.prof, b_add, b_del):
            row.addWidget(w)
        row.addStretch()
        lay.addLayout(row)
        ctl.profiles_changed.connect(self.reload)
        self.reload()

    def reload(self):
        self.prof.clear()
        self.prof.addItems(list(profiles.load()))
        self.list.clear()
        for e in settings.get("schedule"):
            it = QListWidgetItem(f"{e['at']}  →  {e['profile']}")
            it.setData(Qt.ItemDataRole.UserRole, e["at"])
            self.list.addItem(it)

    def _add(self):
        if not self.prof.currentText():
            QMessageBox.information(self, "Schedule", "Save a profile first.")
            return
        schedule.add(self.at.time().toString("HH:mm"), self.prof.currentText())
        self.reload()

    def _remove(self):
        it = self.list.currentItem()
        if it:
            schedule.remove(it.data(Qt.ItemDataRole.UserRole))
            self.reload()


class Window(QWidget):
    def __init__(self, ctl: Controller):
        super().__init__()
        self.ctl = ctl
        self.setWindowTitle("monctl")
        self.setWindowIcon(QIcon.fromTheme("video-display"))
        self.lay = QVBoxLayout(self)

        bar = QHBoxLayout()
        self.prof = QComboBox()
        self.prof.setMinimumWidth(160)
        b_apply, b_save, b_del = QPushButton("Apply"), QPushButton("Save as…"), QPushButton("Delete")
        b_apply.clicked.connect(self._apply)
        b_save.clicked.connect(self._save)
        b_del.clicked.connect(self._delete)
        bar.addWidget(QLabel("Profile:"))
        for w in (self.prof, b_apply, b_save, b_del):
            bar.addWidget(w)
        bar.addStretch()
        b_ref = QPushButton(QIcon.fromTheme("view-refresh"), "")
        if b_ref.icon().isNull():
            b_ref.setText("↻")
        b_ref.setToolTip("Re-detect monitors")
        b_ref.clicked.connect(ctl.refresh)
        bar.addWidget(b_ref)
        self.lay.addLayout(bar)

        allrow = QHBoxLayout()
        self.all = QSlider(Qt.Orientation.Horizontal)
        self.all.setRange(0, 100)
        self.all.setPageStep(10)
        self.all_val = QLabel("–")
        self.all_val.setMinimumWidth(36)
        self.all.valueChanged.connect(lambda v: self.all_val.setText(f"{v}%"))
        self.all.sliderReleased.connect(lambda: self.ctl.set_level(self.all.value(), quiet=True))
        self.all.actionTriggered.connect(lambda _a: QTimer.singleShot(
            0, lambda: None if self.all.isSliderDown() else self.ctl.set_level(self.all.value(), quiet=True)))
        allrow.addWidget(QLabel("All monitors:"))
        allrow.addWidget(self.all)
        allrow.addWidget(self.all_val)
        self.lay.addLayout(allrow)

        self.boxes_lay = QVBoxLayout()
        self.lay.addLayout(self.boxes_lay)
        self.auto = AutoBox(ctl)
        self.lay.addWidget(self.auto)
        self.sched = ScheduleBox(ctl)
        self.lay.addWidget(self.sched)
        self.status = QLabel("Detecting monitors…")
        self.lay.addWidget(self.status)
        self.boxes: dict[str, MonitorBox] = {}

        ctl.monitors_changed.connect(self._rebuild)
        ctl.state_changed.connect(lambda k, st: k in self.boxes and self.boxes[k].show_state(st))
        ctl.state_changed.connect(lambda *_: self._show_level())
        ctl.levels_changed.connect(self._show_level)
        ctl.busy.connect(lambda b: self.status.setText("Working…" if b else "Ready"))
        ctl.profiles_changed.connect(lambda: self._load_profiles(self.prof.currentText()))
        self._load_profiles()
        if ctl.monitors:
            self._rebuild(ctl.monitors)
            for k, st in ctl.states.items():
                if k in self.boxes:
                    self.boxes[k].show_state(st)

    def _rebuild(self, mons):
        for b in self.boxes.values():
            b.deleteLater()
        self.boxes = {}
        for m in mons:
            b = MonitorBox(self.ctl, m)
            self.boxes_lay.addWidget(b)
            self.boxes[m.key] = b
        if not mons:
            self.status.setText("No monitors found")

    def _show_level(self):
        lv = self.ctl._level if self.ctl._level is not None else self.ctl.level()
        if lv is not None and not self.all.isSliderDown():
            self.all.blockSignals(True)
            self.all.setValue(lv)
            self.all.blockSignals(False)
            self.all_val.setText(f"{lv}%")

    def _load_profiles(self, select: str | None = None):
        self.prof.clear()
        self.prof.addItems(list(profiles.load()))
        if select:
            self.prof.setCurrentText(select)

    def _apply(self):
        if self.prof.currentText():
            self.ctl.apply_profile(self.prof.currentText())

    def _save(self):
        name, ok = QInputDialog.getText(self, "Save profile", "Profile name:",
                                        text=self.prof.currentText())
        if ok and name.strip():
            self.ctl.save_profile(name.strip(), on_done=self._load_profiles)

    def _delete(self):
        name = self.prof.currentText()
        if name and QMessageBox.question(self, "Delete profile", f"Delete {name!r}?") \
                == QMessageBox.StandardButton.Yes:
            profiles.delete(name)
            self.ctl.profiles_changed.emit()


# ------------------------------------------------------------------- tray

class Tray(QSystemTrayIcon):
    def __init__(self, ctl: Controller):
        super().__init__(QIcon.fromTheme("video-display"))
        self.ctl = ctl
        self.window: Window | None = None
        self.setToolTip(f"monctl {__version__}")
        self.menu = QMenu()
        self.setContextMenu(self.menu)
        self.menu.aboutToShow.connect(self._build)
        self.activated.connect(lambda r: r == QSystemTrayIcon.ActivationReason.Trigger
                               and self.open_window())
        ctl.error.connect(lambda msg: self.showMessage(
            "monctl", msg, QSystemTrayIcon.MessageIcon.Warning, 6000))
        ctl.auto_switched.connect(lambda n: self.showMessage(
            "monctl", f"Switched to {n}", QSystemTrayIcon.MessageIcon.Information, 2500))
        ctl.notice.connect(lambda msg: self.showMessage(
            "monctl", msg, QSystemTrayIcon.MessageIcon.Information, 1500))
        self.keys: shortcuts.PortalShortcuts | None = None
        if settings.get("shortcuts"):
            self.start_shortcuts()
        self._build()

    # -- global shortcuts -------------------------------------------------
    ACTIONS = {
        "profile-1": lambda c: c.apply_profile_at(0), "profile-2": lambda c: c.apply_profile_at(1),
        "profile-3": lambda c: c.apply_profile_at(2), "profile-4": lambda c: c.apply_profile_at(3),
        "profile-next": lambda c: c.next_profile(),
        "brightness-up": lambda c: c.step_brightness(+10),
        "brightness-down": lambda c: c.step_brightness(-10),
        "auto-toggle": lambda c: c.toggle_auto(),
    }

    def start_shortcuts(self):
        if self.keys is not None:
            return
        self.keys = shortcuts.PortalShortcuts(
            on_activated=lambda sid: sid in self.ACTIONS and self.ACTIONS[sid](self.ctl),
            on_error=self.ctl.error.emit)
        self.keys.start()

    def set_shortcuts(self, on: bool):
        settings.set(shortcuts=on)
        if on:
            self.start_shortcuts()
        elif self.keys is not None:
            self.keys.stop()
            self.keys = None

    def open_window(self):
        if self.window is None:
            self.window = Window(self.ctl)
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()

    def _build(self):
        m = self.menu
        m.clear()
        profs = list(profiles.load())
        sec = m.addSection("Profiles")
        sec.setText("Profiles")
        for name in profs:
            m.addAction(name, lambda n=name: self.ctl.apply_profile(
                n, on_done=lambda n: self.showMessage("monctl", f"Applied {n}",
                                                      QSystemTrayIcon.MessageIcon.Information, 2000)))
        if not profs:
            m.addAction("(none yet)").setEnabled(False)
        m.addAction("Save current as…", self._save_profile)
        auto = m.addAction("Automatic profiles")
        auto.setCheckable(True)
        auto.setChecked(bool(settings.get("auto_enabled")))
        auto.toggled.connect(lambda on: (settings.set(auto_enabled=on), self.ctl.profiles_changed.emit()))

        m.addSeparator()
        if not self.ctl.monitors:
            m.addAction("Detecting monitors…").setEnabled(False)
        b = m.addMenu("Brightness (all)")
        for v in (100, 75, 50, 25, 10):
            b.addAction(f"{v}%", lambda v=v: self.ctl.set_level(v))
        for mon in self.ctl.monitors:
            if mon.msi or self.ctl.inputs.get(mon.key):
                sub = m.addMenu(mon.label)
                if mon.msi:
                    self._msi_menu(sub, mon)
                self._input_menu(sub, mon)

        m.addSeparator()
        m.addAction("Open window…", self.open_window)
        m.addAction("Re-detect monitors", self.ctl.refresh)
        k = m.addAction("Keyboard shortcuts")
        k.setCheckable(True)
        k.setChecked(self.keys is not None)
        reason = shortcuts.unavailable_reason()
        if reason:
            k.setEnabled(False)
            k.setToolTip(reason)
        k.toggled.connect(self.set_shortcuts)
        if self.keys is not None and self.keys.session is not None:
            m.addAction("Change shortcuts…", self.keys.configure)
        a = m.addAction("Start at login")
        a.setCheckable(True)
        a.setChecked(autostart_path().is_file())
        a.toggled.connect(set_autostart)
        m.addAction("Quit", QApplication.quit)

    def _msi_menu(self, menu: QMenu, mon: Monitor):
        st = self.ctl.states.get(mon.key, {})
        for key in ("game_mode", "night_vision", "smart_crosshair_icon", "eye_saver"):
            sub = menu.addMenu(LABELS[key])
            grp = QActionGroup(sub)
            for v in msi.WRITABLE[key]:
                a = QAction(nice(v), sub, checkable=True, checked=st.get(key) == v)
                a.triggered.connect(lambda _c=False, k=key, v=v: self.ctl.apply(mon, {k: v}))
                grp.addAction(a)
                sub.addAction(a)

    def _input_menu(self, menu: QMenu, mon: Monitor):
        ins = self.ctl.inputs.get(mon.key) or []
        if not ins:
            return
        sub = menu.addMenu("Input")
        cur = self.ctl.states.get(mon.key, {}).get("input")
        grp = QActionGroup(sub)
        for v in ins:
            a = QAction(INPUT_LABELS.get(v, v), sub, checkable=True, checked=cur == v)
            a.triggered.connect(lambda _c=False, v=v: v != cur and confirm_input(None, mon, v)
                                and self.ctl.apply(mon, {"input": v}))
            grp.addAction(a)
            sub.addAction(a)

    def _save_profile(self):
        name, ok = QInputDialog.getText(None, "Save profile", "Profile name:")
        if ok and name.strip():
            self.ctl.save_profile(name.strip(), on_done=lambda n: self.showMessage(
                "monctl", f"Saved {n}", QSystemTrayIcon.MessageIcon.Information, 2000))


def log_path() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "monctl" / "tray.log"


def install_excepthook(notify=None):
    """Log unhandled errors instead of aborting.

    PyQt6 calls qFatal() (abort) when a slot raises and sys.excepthook is the
    default, which kills the tray. Log the traceback and keep running.
    """
    def hook(etype, value, tb):
        text = "".join(traceback.format_exception(etype, value, tb))
        print(text, file=sys.stderr, flush=True)
        try:
            log_path().parent.mkdir(parents=True, exist_ok=True)
            import time
            with open(log_path(), "a") as f:
                f.write(f"--- {time.strftime('%Y-%m-%d %H:%M:%S')} monctl {__version__}\n{text}")
        except OSError:
            pass
        if notify:
            try:
                notify(f"Internal error: {value}  (details in {log_path()})")
            except Exception:  # noqa: BLE001 - never let the hook itself raise
                pass
    sys.excepthook = hook
    return hook


def run_tray(open_window: bool = False) -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("monctl")
    app.setDesktopFileName("monctl")
    app.setQuitOnLastWindowClosed(False)
    ctl = Controller()
    if not QSystemTrayIcon.isSystemTrayAvailable():
        print("monctl: no system tray; opening the window instead", file=sys.stderr)
        open_window = True
    tray = Tray(ctl)
    install_excepthook(lambda msg: tray.showMessage(
        "monctl", msg, QSystemTrayIcon.MessageIcon.Warning, 8000))
    app.aboutToQuit.connect(ctl.shutdown)
    tray.show()
    if open_window:
        tray.open_window()
        app.setQuitOnLastWindowClosed(not QSystemTrayIcon.isSystemTrayAvailable())
    ctl.refresh()
    return app.exec()
