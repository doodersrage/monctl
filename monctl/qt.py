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
from PyQt6.QtWidgets import (QApplication, QComboBox, QFormLayout, QGroupBox, QHBoxLayout,
                             QInputDialog, QLabel, QMenu, QMessageBox, QPushButton, QSlider,
                             QSystemTrayIcon, QVBoxLayout, QWidget)

from . import __version__, msi, profiles, runner
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

    def __init__(self):
        super().__init__()
        self.pool = QThreadPool()
        self.pool.setMaxThreadCount(1)
        self.monitors: list[Monitor] = []
        self.states: dict[str, dict] = {}
        self._jobs: set[_Job] = set()
        self._pending = 0

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
            return mons, {m.key: m.state() for m in mons}

        def done(res):
            self.monitors, self.states = res
            self.monitors_changed.emit(self.monitors)
            for k, st in self.states.items():
                self.state_changed.emit(k, st)
        self._submit(work, done)

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

    def apply_profile(self, name: str, on_done=None):
        mons = list(self.monitors)

        def work():
            warns = profiles.apply(name, mons)
            return warns, {m.key: m.state() for m in mons}

        def done(res):
            warns, states = res
            self.states.update(states)
            for k, st in states.items():
                self.state_changed.emit(k, st)
            if warns:
                self.error.emit("\n".join(warns))
            if on_done:
                on_done(name)
        self._submit(work, done)

    def save_profile(self, name: str, on_done=None):
        mons = list(self.monitors)
        self._submit(lambda: profiles.save(name, mons), lambda _r: on_done and on_done(name))


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
        self.combos: dict[str, QComboBox] = {}
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
                i = c.findData(st.get(key))
                if i >= 0:
                    c.setCurrentIndex(i)
            self.setEnabled(True)
        finally:
            self.updating = False


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

        self.boxes_lay = QVBoxLayout()
        self.lay.addLayout(self.boxes_lay)
        self.status = QLabel("Detecting monitors…")
        self.lay.addWidget(self.status)
        self.boxes: dict[str, MonitorBox] = {}

        ctl.monitors_changed.connect(self._rebuild)
        ctl.state_changed.connect(lambda k, st: k in self.boxes and self.boxes[k].show_state(st))
        ctl.busy.connect(lambda b: self.status.setText("Working…" if b else "Ready"))
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
            self._load_profiles()


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
        self._build()

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

        m.addSeparator()
        if not self.ctl.monitors:
            m.addAction("Detecting monitors…").setEnabled(False)
        b = m.addMenu("Brightness (all)")
        for v in (100, 75, 50, 25, 10):
            b.addAction(f"{v}%", lambda v=v: [self.ctl.apply(x, {"brightness": v})
                                              for x in self.ctl.monitors])
        for mon in self.ctl.monitors:
            if mon.msi:
                self._msi_menu(m.addMenu(mon.label), mon)

        m.addSeparator()
        m.addAction("Open window…", self.open_window)
        m.addAction("Re-detect monitors", self.ctl.refresh)
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

    def _save_profile(self):
        name, ok = QInputDialog.getText(None, "Save profile", "Profile name:")
        if ok and name.strip():
            self.ctl.save_profile(name.strip(), on_done=lambda n: self.showMessage(
                "monctl", f"Saved {n}", QSystemTrayIcon.MessageIcon.Information, 2000))


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
    tray.show()
    if open_window:
        tray.open_window()
        app.setQuitOnLastWindowClosed(not QSystemTrayIcon.isSystemTrayAvailable())
    ctl.refresh()
    return app.exec()
