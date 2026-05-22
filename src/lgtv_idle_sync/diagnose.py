#!/usr/bin/env python3
"""
Event monitor for lgtv-idle-sync.

Subscribes to every DBus signal, property change, and Wayland event that
matters for idle/inhibit/suspend behaviour, and logs them in real time
with timestamps.

Trigger system events while this runs to build a "story" of what fires:

  - Go idle (stop touching mouse/keyboard)
  - Resume from idle
  - Play / pause a video in a browser
  - Play / pause audio in a music player
  - Open / close a fullscreen app
  - Suspend the system (systemctl suspend)
  - Resume from suspend
  - Lock / unlock the screen

Run with:  uv run python -m lgtv_idle_sync.diagnose
"""

import asyncio
import os
import sys
import time

# ---------------------------------------------------------------------------
# Logging setup — all events go through this
# ---------------------------------------------------------------------------

_T0 = time.monotonic()


def _ts() -> str:
    return f"{time.monotonic() - _T0:10.3f}s"


def event(source: str, name: str, detail: str = ""):
    """Print a timestamped event line."""
    line = f"[{_ts()}] [{source:^30}] {name}"
    if detail:
        line += f"  |  {detail}"
    print(line, flush=True)


def _truncate(v, maxlen=200) -> str:
    s = str(v)
    return s if len(s) <= maxlen else s[:maxlen] + "…"


# ---------------------------------------------------------------------------
# 1. Wayland: ext_idle_notifier_v1
# ---------------------------------------------------------------------------

WAYLAND_IDLE_TIMEOUT_MS = 5000  # short timeout to see events quickly


async def watch_wayland_idle():
    """Watch idle/resumed events from the Wayland compositor."""
    source = "wayland/idle-notify"
    try:
        from pywayland.client import Display
        from pywayland.protocol.ext_idle_notify_v1 import ext_idle_notifier_v1
        from pywayland.protocol.wayland import WlSeat

        display = Display()
        display.connect()
        fd = display.get_fd()
        registry = display.get_registry()

        notifier = None
        seat = None

        def on_global(reg, gname, iface, version):
            nonlocal notifier, seat
            if iface == "ext_idle_notifier_v1":
                notifier = reg.bind(gname, ext_idle_notifier_v1.ExtIdleNotifierV1, version)
            elif iface == "wl_seat":
                seat = reg.bind(gname, WlSeat, version)

        registry.dispatcher["global"] = on_global
        display.roundtrip()

        if not notifier or not seat:
            event(source, "UNAVAILABLE",
                  f"notifier={'yes' if notifier else 'no'} seat={'yes' if seat else 'no'}")
            return

        def make_notification():
            n = notifier.get_idle_notification(WAYLAND_IDLE_TIMEOUT_MS, seat)
            n.dispatcher["idled"] = lambda *a: on_idled(n)
            n.dispatcher["resumed"] = lambda *a: on_resumed(n)
            display.flush()
            return n

        def on_idled(n):
            event(source, "IDLED", f"after {WAYLAND_IDLE_TIMEOUT_MS}ms timeout")

        def on_resumed(n):
            event(source, "RESUMED", "user activity detected")

        notification = make_notification()
        event(source, "LISTENING",
              f"timeout={WAYLAND_IDLE_TIMEOUT_MS}ms")

        loop = asyncio.get_running_loop()
        while True:
            ev = asyncio.Event()
            loop.add_reader(fd, ev.set)
            try:
                await ev.wait()
            finally:
                loop.remove_reader(fd)
            display.dispatch(block=True)

    except Exception as e:
        event(source, "ERROR", str(e))


# ---------------------------------------------------------------------------
# 2. DBus session bus: org.freedesktop.PowerManagement.Inhibit
# ---------------------------------------------------------------------------

async def watch_power_management_inhibit():
    source = "dbus/PowerMgmt.Inhibit"
    try:
        from dbus_fast.aio import MessageBus

        bus = await MessageBus().connect()
        name = "org.freedesktop.PowerManagement.Inhibit"
        path = "/org/freedesktop/PowerManagement/Inhibit"

        intro = await bus.introspect(name, path)
        proxy = bus.get_proxy_object(name, path, intro)
        iface = proxy.get_interface(name)

        initial = await iface.call_has_inhibit()
        event(source, "INITIAL STATE", f"has_inhibit={initial}")

        def on_changed(has_inhibit):
            event(source, "HAS_INHIBIT_CHANGED", f"has_inhibit={has_inhibit}")

        iface.on_has_inhibit_changed(on_changed)
        event(source, "LISTENING")
        await bus.wait_for_disconnect()

    except Exception as e:
        event(source, "UNAVAILABLE", str(e))


# ---------------------------------------------------------------------------
# 3. DBus session bus: org.freedesktop.ScreenSaver
# ---------------------------------------------------------------------------

async def watch_screensaver():
    source = "dbus/ScreenSaver"
    try:
        from dbus_fast.aio import MessageBus

        bus = await MessageBus().connect()
        name = "org.freedesktop.ScreenSaver"
        path = "/org/freedesktop/ScreenSaver"

        intro = await bus.introspect(name, path)
        proxy = bus.get_proxy_object(name, path, intro)
        iface = proxy.get_interface(name)

        # ScreenSaver has ActiveChanged signal
        try:
            active = await iface.call_get_active()
            event(source, "INITIAL STATE", f"active={active}")
        except Exception:
            pass

        def on_active_changed(active):
            event(source, "ACTIVE_CHANGED", f"active={active}")

        try:
            iface.on_active_changed(on_active_changed)
        except Exception:
            pass

        event(source, "LISTENING")
        await bus.wait_for_disconnect()

    except Exception as e:
        event(source, "UNAVAILABLE", str(e))


# ---------------------------------------------------------------------------
# 4. DBus session bus: KDE PolicyAgent
# ---------------------------------------------------------------------------

async def watch_kde_policy_agent():
    source = "dbus/KDE.PolicyAgent"
    try:
        from dbus_fast.aio import MessageBus

        bus = await MessageBus().connect()
        pa_path = "/org/kde/Solid/PowerManagement/PolicyAgent"
        pa_iface_name = "org.kde.Solid.PowerManagement.PolicyAgent"

        intro = await bus.introspect("org.kde.Solid.PowerManagement", pa_path)
        proxy = bus.get_proxy_object("org.kde.Solid.PowerManagement", pa_path, intro)
        iface = proxy.get_interface(pa_iface_name)

        # Check initial state via HasInhibition for each type
        type_names = {1: "ChangeProfile", 2: "ChangeScreenSettings", 4: "InterruptSession"}
        for bit, tname in type_names.items():
            try:
                has = await iface.call_has_inhibition(bit)
                event(source, f"HasInhibition({tname})", str(has))
            except Exception as e:
                event(source, f"HasInhibition({tname})", f"error: {e}")

        # Read ActiveInhibitions property (emits-change — more useful than signal)
        props = proxy.get_interface("org.freedesktop.DBus.Properties")
        try:
            active = await props.call_get(pa_iface_name, "ActiveInhibitions")
            for entry in (active.value if hasattr(active, "value") else active):
                event(source, "ACTIVE INHIBITION", _truncate(entry))
        except Exception as e:
            event(source, "ActiveInhibitions", f"error: {e}")

        # Watch property changes (ActiveInhibitions, RequestedInhibitions)
        def on_props_changed(iface_name, changed, invalidated):
            for k, v in changed.items():
                val = v.value if hasattr(v, "value") else v
                if isinstance(val, list):
                    event(source, f"PROP CHANGED: {k}", f"{len(val)} entries")
                    for entry in val:
                        event(source, f"  {k}", _truncate(entry))
                else:
                    event(source, f"PROP CHANGED: {k}", _truncate(val))
            for k in invalidated:
                event(source, f"PROP INVALIDATED: {k}")

        props.on_properties_changed(on_props_changed)

        event(source, "LISTENING")
        await bus.wait_for_disconnect()

    except Exception as e:
        event(source, "UNAVAILABLE", str(e))


# ---------------------------------------------------------------------------
# 5. DBus session bus: org.freedesktop.portal.Inhibit  (StateChanged)
# ---------------------------------------------------------------------------

async def watch_portal_inhibit():
    source = "dbus/portal.Inhibit"
    try:
        from dbus_fast.aio import MessageBus

        bus = await MessageBus().connect()
        name = "org.freedesktop.portal.Desktop"
        path = "/org/freedesktop/portal/desktop"

        intro = await bus.introspect(name, path)
        proxy = bus.get_proxy_object(name, path, intro)

        try:
            iface = proxy.get_interface("org.freedesktop.portal.Inhibit")

            def on_state_changed(session_handle, state):
                event(source, "STATE_CHANGED",
                      f"session={session_handle} state={_truncate(state)}")

            iface.on_state_changed(on_state_changed)
            event(source, "LISTENING")
        except Exception as e:
            event(source, "SIGNAL BIND FAILED", str(e))

        await bus.wait_for_disconnect()

    except Exception as e:
        event(source, "UNAVAILABLE", str(e))


# ---------------------------------------------------------------------------
# 6. DBus system bus: logind (PrepareForSleep / PrepareForShutdown)
# ---------------------------------------------------------------------------

async def watch_logind():
    source = "dbus/logind"
    try:
        from dbus_fast.aio import MessageBus
        from dbus_fast import BusType

        bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
        intro = await bus.introspect(
            "org.freedesktop.login1", "/org/freedesktop/login1"
        )
        proxy = bus.get_proxy_object(
            "org.freedesktop.login1", "/org/freedesktop/login1", intro
        )
        iface = proxy.get_interface("org.freedesktop.login1.Manager")

        # List current inhibitors
        try:
            inhibitors = await iface.call_list_inhibitors()
            for who, why, what, mode, uid, pid in inhibitors:
                event(source, "EXISTING INHIBITOR",
                      f"who={who} what={what} why={why} mode={mode} pid={pid}")
        except Exception as e:
            event(source, "LIST INHIBITORS FAILED", str(e))

        def on_sleep(start):
            if start:
                event(source, "PREPARE_FOR_SLEEP", "start=True — about to suspend")
            else:
                event(source, "PREPARE_FOR_SLEEP", "start=False — just resumed")

        def on_shutdown(start):
            if start:
                event(source, "PREPARE_FOR_SHUTDOWN", "start=True — about to shutdown")
            else:
                event(source, "PREPARE_FOR_SHUTDOWN", "start=False — shutdown cancelled")

        iface.on_prepare_for_sleep(on_sleep)
        iface.on_prepare_for_shutdown(on_shutdown)

        # Also watch session property changes (Locked, IdleHint, etc.)
        # by monitoring the user's session object
        try:
            # Try by PID first, fall back to listing sessions for our UID
            try:
                session_path = await iface.call_get_session_by_pid(os.getpid())
            except Exception:
                sessions = await iface.call_list_sessions()
                uid = os.getuid()
                session_path = None
                for sess_id, sess_uid, sess_user, sess_seat, sess_path in sessions:
                    if sess_uid == uid:
                        session_path = sess_path
                        break
                if not session_path:
                    raise RuntimeError(f"no session found for uid {uid}")
            s_intro = await bus.introspect("org.freedesktop.login1", session_path)
            s_proxy = bus.get_proxy_object(
                "org.freedesktop.login1", session_path, s_intro
            )
            s_props = s_proxy.get_interface("org.freedesktop.DBus.Properties")

            # Read initial session properties
            for prop in ("IdleHint", "IdleSinceHint", "LockedHint", "Active",
                         "State", "Type", "Class"):
                try:
                    val = await s_props.call_get("org.freedesktop.login1.Session", prop)
                    event(source, f"SESSION.{prop}", _truncate(val.value))
                except Exception:
                    pass

            def on_session_props_changed(iface_name, changed, invalidated):
                for k, v in changed.items():
                    event(source, f"SESSION PROP CHANGED",
                          f"{k} = {_truncate(v.value if hasattr(v, 'value') else v)}")
                for k in invalidated:
                    event(source, f"SESSION PROP INVALIDATED", k)

            s_props.on_properties_changed(on_session_props_changed)
            event(source, f"LISTENING (session={session_path})")
        except Exception as e:
            event(source, "SESSION WATCH FAILED", str(e))
            event(source, "LISTENING (manager only)")

        await bus.wait_for_disconnect()

    except Exception as e:
        event(source, "ERROR", str(e))


# ---------------------------------------------------------------------------
# 7. DBus session bus: MPRIS media players
# ---------------------------------------------------------------------------

async def watch_mpris():
    source = "dbus/MPRIS"
    try:
        from dbus_fast.aio import MessageBus

        bus = await MessageBus().connect()

        # Track which players we're already watching
        watched: set[str] = set()

        async def watch_player(name: str):
            if name in watched:
                return
            watched.add(name)
            short = name.removeprefix("org.mpris.MediaPlayer2.")
            try:
                intro = await bus.introspect(name, "/org/mpris/MediaPlayer2")
                proxy = bus.get_proxy_object(name, "/org/mpris/MediaPlayer2", intro)
                props = proxy.get_interface("org.freedesktop.DBus.Properties")

                # Read initial state
                try:
                    player = proxy.get_interface("org.mpris.MediaPlayer2.Player")
                    status = await player.get_playback_status()
                    event(source, f"PLAYER FOUND: {short}",
                          f"PlaybackStatus={status}")
                except Exception:
                    event(source, f"PLAYER FOUND: {short}", "cannot read state")

                def on_props_changed(iface_name, changed, invalidated):
                    for k, v in changed.items():
                        val = v.value if hasattr(v, "value") else v
                        if k == "Metadata":
                            # Extract just the interesting bits
                            md = val if isinstance(val, dict) else {}
                            title = md.get("xesam:title", "?")
                            if hasattr(title, "value"):
                                title = title.value
                            artist = md.get("xesam:artist", "?")
                            if hasattr(artist, "value"):
                                artist = artist.value
                            event(source, f"{short}: Metadata",
                                  f"title={_truncate(title, 60)} artist={_truncate(artist, 60)}")
                        else:
                            event(source, f"{short}: {k}", _truncate(val, 120))
                    for k in invalidated:
                        event(source, f"{short}: {k} INVALIDATED")

                props.on_properties_changed(on_props_changed)
            except Exception as e:
                event(source, f"WATCH FAILED: {short}", str(e))

        # Watch for new players appearing/disappearing
        dbus_intro = await bus.introspect(
            "org.freedesktop.DBus", "/org/freedesktop/DBus"
        )
        dbus_proxy = bus.get_proxy_object(
            "org.freedesktop.DBus", "/org/freedesktop/DBus", dbus_intro
        )
        dbus_iface = dbus_proxy.get_interface("org.freedesktop.DBus")

        # Subscribe to existing players
        all_names = await dbus_iface.call_list_names()
        for n in sorted(all_names):
            if n.startswith("org.mpris.MediaPlayer2."):
                await watch_player(n)

        # Watch for new bus names
        def on_name_owner_changed(name, old_owner, new_owner):
            if not name.startswith("org.mpris.MediaPlayer2."):
                return
            short = name.removeprefix("org.mpris.MediaPlayer2.")
            if new_owner and not old_owner:
                event(source, f"PLAYER APPEARED: {short}")
                asyncio.ensure_future(watch_player(name))
            elif old_owner and not new_owner:
                event(source, f"PLAYER DISAPPEARED: {short}")
                watched.discard(name)

        dbus_iface.on_name_owner_changed(on_name_owner_changed)

        if not watched:
            event(source, "NO PLAYERS", "none currently running")
        event(source, "LISTENING")
        await bus.wait_for_disconnect()

    except Exception as e:
        event(source, "ERROR", str(e))


# ---------------------------------------------------------------------------
# 8. PulseAudio / PipeWire sink-input events
# ---------------------------------------------------------------------------

async def watch_pulse():
    source = "pulse/sink-input"
    try:
        from pulsectl_asyncio import PulseAsync
        from pulsectl import PulseEventMaskEnum, PulseEventTypeEnum

        async with PulseAsync("lgtv-diag") as pulse:
            event(source, "CONNECTED")

            type_names = {
                PulseEventTypeEnum.new: "NEW",
                PulseEventTypeEnum.change: "CHANGE",
                PulseEventTypeEnum.remove: "REMOVE",
            }
            async for ev in pulse.subscribe_events(PulseEventMaskEnum.all):
                event(source, f"{type_names.get(ev.t, ev.t)}",
                      f"facility={ev.facility} index={ev.index}")

    except Exception as e:
        event(source, "ERROR", str(e))


# ---------------------------------------------------------------------------
# 9. DBus session bus: org.kde.screensaver (KDE lock screen)
# ---------------------------------------------------------------------------

async def watch_kde_screensaver():
    source = "dbus/kde.screensaver"
    try:
        from dbus_fast.aio import MessageBus

        bus = await MessageBus().connect()
        name = "org.kde.screensaver"
        path = "/ScreenSaver"

        intro = await bus.introspect(name, path)
        proxy = bus.get_proxy_object(name, path, intro)

        # org.freedesktop.ScreenSaver interface on KDE's object
        iface = proxy.get_interface("org.freedesktop.ScreenSaver")

        try:
            active = await iface.call_get_active()
            event(source, "INITIAL STATE", f"active={active}")
        except Exception:
            pass

        def on_active_changed(active):
            event(source, "ACTIVE_CHANGED", f"active={active}")

        try:
            iface.on_active_changed(on_active_changed)
        except Exception:
            pass

        event(source, "LISTENING")
        await bus.wait_for_disconnect()

    except Exception as e:
        event(source, "UNAVAILABLE", str(e))


# ---------------------------------------------------------------------------
# 10. DBus system bus: NetworkManager state changes (for resume story)
# ---------------------------------------------------------------------------

async def watch_network_manager():
    source = "dbus/NetworkManager"
    try:
        from dbus_fast.aio import MessageBus
        from dbus_fast import BusType

        bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
        nm_name = "org.freedesktop.NetworkManager"
        nm_path = "/org/freedesktop/NetworkManager"

        intro = await bus.introspect(nm_name, nm_path)
        proxy = bus.get_proxy_object(nm_name, nm_path, intro)
        props = proxy.get_interface("org.freedesktop.DBus.Properties")

        state_map = {
            0: "UNKNOWN", 10: "ASLEEP", 20: "DISCONNECTED",
            30: "DISCONNECTING", 40: "CONNECTING",
            50: "CONNECTED_LOCAL", 60: "CONNECTED_SITE", 70: "CONNECTED_GLOBAL",
        }
        conn_map = {
            0: "UNKNOWN", 1: "NONE", 2: "PORTAL", 3: "LIMITED", 4: "FULL",
        }

        # Initial state
        try:
            st = await props.call_get(nm_name, "State")
            cn = await props.call_get(nm_name, "Connectivity")
            event(source, "INITIAL STATE",
                  f"State={st.value}({state_map.get(st.value, '?')}) "
                  f"Connectivity={cn.value}({conn_map.get(cn.value, '?')})")
        except Exception as e:
            event(source, "INITIAL STATE", f"error: {e}")

        def on_props_changed(iface_name, changed, invalidated):
            parts = []
            for k, v in changed.items():
                val = v.value if hasattr(v, "value") else v
                if k == "State":
                    parts.append(f"{k}={val}({state_map.get(val, '?')})")
                elif k == "Connectivity":
                    parts.append(f"{k}={val}({conn_map.get(val, '?')})")
                else:
                    parts.append(f"{k}={_truncate(val, 80)}")
            if parts:
                event(source, "PROP CHANGED", "  ".join(parts))

        props.on_properties_changed(on_props_changed)
        event(source, "LISTENING")
        await bus.wait_for_disconnect()

    except Exception as e:
        event(source, "UNAVAILABLE", str(e))


# ---------------------------------------------------------------------------
# 11. DBus session bus: KDE PowerDevil property changes
# ---------------------------------------------------------------------------

async def watch_kde_powerdevil():
    source = "dbus/KDE.PowerDevil"
    try:
        from dbus_fast.aio import MessageBus

        bus = await MessageBus().connect()

        # PowerDevil lives at org.kde.Solid.PowerManagement
        pm_name = "org.kde.Solid.PowerManagement"
        pm_path = "/org/kde/Solid/PowerManagement"

        intro = await bus.introspect(pm_name, pm_path)
        proxy = bus.get_proxy_object(pm_name, pm_path, intro)

        # Listen for ProfileChanged, configurationReloaded etc
        for iface_info in intro.interfaces:
            if "PowerManagement" not in iface_info.name:
                continue
            try:
                iface = proxy.get_interface(iface_info.name)
                for sig in iface_info.signals:
                    try:
                        handler_name = f"on_{_camel_to_snake(sig.name)}"
                        if hasattr(iface, handler_name):
                            def make_handler(sname):
                                def h(*args):
                                    event(source, sname, _truncate(args))
                                return h
                            getattr(iface, handler_name)(make_handler(sig.name))
                    except Exception:
                        pass
                event(source, f"BOUND {iface_info.name}",
                      f"signals={[s.name for s in iface_info.signals]}")
            except Exception:
                pass

        event(source, "LISTENING")
        await bus.wait_for_disconnect()

    except Exception as e:
        event(source, "UNAVAILABLE", str(e))


def _camel_to_snake(name: str) -> str:
    import re
    s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
    return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def async_main():
    print("=" * 72)
    print("  lgtv-idle-sync event monitor")
    print("  Watching all relevant DBus signals, property changes,")
    print("  Wayland idle events, and PulseAudio events.")
    print()
    print("  Trigger events to see what fires:")
    print("    - Stop touching mouse/keyboard (idle)")
    print("    - Move mouse (resume)")
    print("    - Play/pause a video or music")
    print("    - systemctl suspend  (then resume)")
    print("    - Lock/unlock screen")
    print()
    print(f"  Wayland idle timeout set to {WAYLAND_IDLE_TIMEOUT_MS}ms for quick feedback")
    print("  Press Ctrl+C to stop.")
    print("=" * 72)
    print()

    tasks = [
        asyncio.create_task(watch_wayland_idle()),
        asyncio.create_task(watch_power_management_inhibit()),
        asyncio.create_task(watch_screensaver()),
        asyncio.create_task(watch_kde_policy_agent()),
        asyncio.create_task(watch_portal_inhibit()),
        asyncio.create_task(watch_logind()),
        asyncio.create_task(watch_mpris()),
        asyncio.create_task(watch_pulse()),
        asyncio.create_task(watch_kde_screensaver()),
        asyncio.create_task(watch_network_manager()),
        asyncio.create_task(watch_kde_powerdevil()),
    ]

    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        pass


def main():
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        print("\n\nStopped.")


if __name__ == "__main__":
    main()
