"""Which window has focus, on KDE Plasma (Wayland or X11), via a tiny KWin script.

Wayland gives apps no way to see the focused window, but KWin scripts can. monctl loads a
script that calls monctl back over D-Bus with the focused window's class and pid whenever focus
changes. Only used when an automatic-profile rule asks for "only while focused".
"""

from __future__ import annotations

import os
from pathlib import Path

SERVICE = "io.github.doodersrage.monctl"
IFACE = "io.github.doodersrage.monctl.Focus"
PLUGIN = "monctl-focus"
SCRIPT = f"""\
function report(w) {{
    callDBus("{SERVICE}", "/Focus", "{IFACE}", "Active",
             w ? String(w.resourceClass || "") : "", w ? (w.pid || 0) : 0);
}}
workspace.windowActivated.connect(report);
report(workspace.activeWindow);
"""


def unavailable_reason() -> str | None:
    try:
        import dbus  # noqa: F401
        import dbus.service  # noqa: F401
        from dbus.mainloop.glib import DBusGMainLoop  # noqa: F401
    except ImportError:
        return "needs python-dbus (dbus-python) and python-gobject"
    if "KDE" not in os.environ.get("XDG_CURRENT_DESKTOP", "").upper():
        return "needs KDE Plasma (KWin)"
    return None


def script_path() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "monctl" / "kwin-focus.js"


class FocusTracker:
    def __init__(self, on_change=None):
        self.on_change = on_change
        self.pid: int | None = None
        self.window_class = ""
        self._bus = self._kwin = self._name = self._obj = None

    def start(self) -> None:
        import dbus
        import dbus.service
        from dbus.mainloop.glib import DBusGMainLoop
        DBusGMainLoop(set_as_default=True)
        self._bus = dbus.SessionBus()
        tracker = self

        class _Focus(dbus.service.Object):
            @dbus.service.method(IFACE, in_signature="si")
            def Active(self, cls, pid):  # noqa: N802 - D-Bus method name
                tracker._active(str(cls), int(pid))

        self._name = dbus.service.BusName(SERVICE, self._bus, do_not_queue=True)
        self._obj = _Focus(self._bus, "/Focus")
        p = script_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(SCRIPT)
        self._kwin = dbus.Interface(self._bus.get_object("org.kde.KWin", "/Scripting"),
                                    "org.kde.kwin.Scripting")
        if self._kwin.isScriptLoaded(PLUGIN):       # left over from a previous run
            self._kwin.unloadScript(PLUGIN)
        self._kwin.loadScript(str(p), PLUGIN, signature="ss")
        self._kwin.start()

    def _active(self, cls: str, pid: int) -> None:
        self.window_class, self.pid = cls, (pid or None)
        if self.on_change:
            self.on_change(self.pid)

    def stop(self) -> None:
        try:
            if self._kwin is not None and self._kwin.isScriptLoaded(PLUGIN):
                self._kwin.unloadScript(PLUGIN)
        except Exception:  # noqa: BLE001 - KWin gone (logout): nothing to clean up
            pass
        if self._obj is not None:
            self._obj.remove_from_connection()
        self._kwin = self._obj = self._name = None
        self.pid = None
