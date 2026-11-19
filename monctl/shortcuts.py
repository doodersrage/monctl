"""Global keyboard shortcuts through the XDG GlobalShortcuts portal (KDE Plasma 6, GNOME 48+).

Uses dbus-python with the GLib main loop; Qt runs on the GLib event dispatcher on Linux, so
portal signals arrive inside the tray's event loop. The desktop asks the user to confirm the
shortcuts the first time they are bound and remembers the answer afterwards.
"""

from __future__ import annotations

import random

# id, description, suggested trigger (the desktop may ignore it or let the user change it)
SHORTCUTS = [
    ("profile-1", "Apply profile 1", "LOGO+ALT+1"),
    ("profile-2", "Apply profile 2", "LOGO+ALT+2"),
    ("profile-3", "Apply profile 3", "LOGO+ALT+3"),
    ("profile-4", "Apply profile 4", "LOGO+ALT+4"),
    ("profile-next", "Switch to the next profile", "LOGO+ALT+n"),
    ("brightness-up", "Brightness up (all monitors)", "LOGO+ALT+Page_Up"),
    ("brightness-down", "Brightness down (all monitors)", "LOGO+ALT+Page_Down"),
    ("auto-toggle", "Turn automatic profiles on/off", "LOGO+ALT+a"),
]
APP_ID = "monctl"  # matches monctl.desktop
_BUS = "org.freedesktop.portal.Desktop"
_PATH = "/org/freedesktop/portal/desktop"
_IFACE = "org.freedesktop.portal.GlobalShortcuts"


def unavailable_reason() -> str | None:
    try:
        import dbus  # noqa: F401
        from dbus.mainloop.glib import DBusGMainLoop  # noqa: F401
    except ImportError:
        return "needs python-dbus (dbus-python) and python-gobject"
    return None


class PortalShortcuts:
    """Bind SHORTCUTS once; call on_activated(shortcut_id) for every press."""

    def __init__(self, on_activated, on_error, on_bound=None):
        self.on_activated, self.on_error, self.on_bound = on_activated, on_error, on_bound
        self.bus = None
        self.session = None
        self.bound: dict[str, str] = {}     # id -> trigger the desktop reports
        self._receivers = []

    # -- plumbing ---------------------------------------------------------
    def _portal(self, iface=_IFACE):
        import dbus
        return dbus.Interface(self.bus.get_object(_BUS, _PATH), iface)

    def _request(self, method: str, args: tuple, options: dict, on_response):
        """Call a portal method that answers through an org.freedesktop.portal.Request."""
        token = f"monctl{random.randrange(1 << 30)}"
        options = dict(options, handle_token=token)
        sender = self.bus.get_unique_name()[1:].replace(".", "_")
        path = f"/org/freedesktop/portal/desktop/request/{sender}/{token}"
        holder = {}

        def response(code, results):
            holder["match"].remove()
            if int(code) == 0:
                on_response(results)
            elif int(code) == 1:
                self.on_error("Keyboard shortcuts were not allowed")
            else:
                self.on_error(f"Keyboard shortcuts: {method} failed")
        # subscribe before calling, so a fast reply is not missed
        holder["match"] = self.bus.add_signal_receiver(
            response, "Response", "org.freedesktop.portal.Request", path=path)
        getattr(self._portal(), method)(*args, options,
                                        reply_handler=lambda *_: None,
                                        error_handler=lambda e: self.on_error(f"Keyboard shortcuts: {e}"))

    # -- API --------------------------------------------------------------
    def start(self) -> None:
        reason = unavailable_reason()
        if reason:
            self.on_error(f"Keyboard shortcuts {reason}")
            return
        import dbus
        from dbus.mainloop.glib import DBusGMainLoop
        DBusGMainLoop(set_as_default=True)
        try:
            self.bus = dbus.SessionBus()
            try:   # unsandboxed apps tell the portal who they are (xdg-desktop-portal >= 1.19)
                self._portal("org.freedesktop.host.portal.Registry").Register(APP_ID, {})
            except dbus.DBusException:
                pass
            self._receivers.append(self.bus.add_signal_receiver(
                self._activated, "Activated", _IFACE))
            self._request("CreateSession", (), {"session_handle_token": f"monctl{random.randrange(1 << 30)}"},
                          self._created)
        except dbus.DBusException as e:
            self.on_error(f"Keyboard shortcuts: {e.get_dbus_message() or e}")

    def _created(self, results):
        import dbus
        self.session = dbus.ObjectPath(results["session_handle"])
        items = dbus.Array([dbus.Struct((sid, {"description": desc, "preferred_trigger": trig}),
                                        signature="sa{sv}") for sid, desc, trig in SHORTCUTS],
                           signature="(sa{sv})")
        self._request("BindShortcuts", (self.session, items, ""), {}, self._bound)

    def _bound(self, results):
        self.bound = {str(sid): str(opts.get("trigger_description", ""))
                      for sid, opts in results.get("shortcuts", [])}
        if self.on_bound:
            self.on_bound(self.bound)

    def _activated(self, session, sid, _timestamp, _options):
        if self.session is not None and str(session) == str(self.session):
            self.on_activated(str(sid))

    def configure(self) -> None:
        """Open the desktop's shortcut editor (portal version 2)."""
        if self.session is None:
            return
        try:
            self._portal().ConfigureShortcuts(self.session, "", {},
                                              reply_handler=lambda *_: None,
                                              error_handler=lambda e: self.on_error(f"Keyboard shortcuts: {e}"))
        except Exception as e:  # noqa: BLE001 - older portals lack ConfigureShortcuts
            self.on_error(f"Can't open the shortcut editor: {e}")

    def stop(self) -> None:
        for r in self._receivers:
            r.remove()
        self._receivers.clear()
        if self.session is not None and self.bus is not None:
            try:
                self.bus.get_object(_BUS, self.session).Close(dbus_interface="org.freedesktop.portal.Session")
            except Exception:  # noqa: BLE001 - closing a dead session is fine
                pass
        self.session = None
