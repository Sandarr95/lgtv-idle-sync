import asyncio
import enum
import logging
import re

from dbus_fast import Message
from dbus_fast.aio import MessageBus

logger = logging.getLogger(__name__)

POLICY_AGENT_BUS_NAME = "org.kde.Solid.PowerManagement"
POLICY_AGENT_PATH = "/org/kde/Solid/PowerManagement/PolicyAgent"
POLICY_AGENT_IFACE = "org.kde.Solid.PowerManagement.PolicyAgent"
DBUS_PROPERTIES_IFACE = "org.freedesktop.DBus.Properties"

KWIN_BUS_NAME = "org.kde.KWin"
KWIN_PATH = "/KWin"
KWIN_IFACE = "org.kde.KWin"

KWIN_WINDOWS_RUNNER_PATH = "/WindowsRunner"
KWIN_WINDOWS_RUNNER_IFACE = "org.kde.krunner1"

# Regex to extract UUID from WindowsRunner match ID format: "{desktopIndex}_{uuid}"
_UUID_RE = re.compile(r'\{([0-9a-f-]+)\}')


class State(enum.Enum):
    ACTIVE = "active"
    SUPPRESSED = "suppressed"
    IDLE = "idle"


def _is_audio_only(why: str) -> bool:
    """Return True if the inhibition reason indicates audio-only playback."""
    why_lower = why.lower()
    return "audio" in why_lower and "video" not in why_lower


class IdlePolicy:
    def __init__(self, wayland_idle_manager, idle_fn, resume_fn):
        self._wayland_mgr = wayland_idle_manager
        self._idle_fn = idle_fn
        self._resume_fn = resume_fn
        self._state = State.ACTIVE
        self._sleeping = False
        self._message_bus = None
        self._policy_agent_props = None
        self._kwin_iface = None
        self._kwin_available = False

    @property
    def state(self):
        return self._state

    def set_sleeping(self, sleeping: bool):
        """Called by SleepNotifier to suppress spurious resume during sleep."""
        self._sleeping = sleeping

    def on_idled(self):
        """Called by WaylandIdleManager when the idle timeout fires."""
        if self._state != State.ACTIVE:
            logger.debug(f"on_idled ignored (state={self._state.value})")
            return
        asyncio.ensure_future(self._evaluate_idle())

    def on_resumed(self):
        """Called by WaylandIdleManager when user input is detected."""
        if self._sleeping:
            logger.debug("on_resumed ignored (system is sleeping)")
            return
        prev = self._state
        self._state = State.ACTIVE
        if prev != State.ACTIVE:
            logger.info(f"Resumed from {prev.value}")
            asyncio.ensure_future(self._safe_resume())

    async def _safe_resume(self):
        try:
            await asyncio.to_thread(self._resume_fn)
        except Exception:
            logger.debug("Resume failed (likely network down during sleep transition)")

    async def _evaluate_idle(self):
        """Decide whether to transition to IDLE or SUPPRESSED."""
        try:
            if await self._should_suppress():
                self._state = State.SUPPRESSED
                logger.info("Suppressed: fullscreen app is inhibiting")
            else:
                self._state = State.IDLE
                logger.info("Idle: turning off screen")
                await asyncio.to_thread(self._idle_fn)
        except Exception:
            logger.exception("Error evaluating idle policy, defaulting to suppress")
            self._state = State.SUPPRESSED

    async def _is_window_fullscreen(self, uuid: str) -> bool:
        """Check if a single window (by UUID) is fullscreen."""
        try:
            raw_info = await self._kwin_iface.call_get_window_info(uuid)
            fullscreen = raw_info.get("fullscreen", False)
            if hasattr(fullscreen, "value"):
                fullscreen = fullscreen.value
            return bool(fullscreen)
        except Exception:
            return False

    async def _query_windows(self, query: str) -> list[str]:
        """Query WindowsRunner and return a list of window UUIDs."""
        try:
            reply = await self._message_bus.call(Message(
                destination=KWIN_BUS_NAME,
                path=KWIN_WINDOWS_RUNNER_PATH,
                interface=KWIN_WINDOWS_RUNNER_IFACE,
                member="Match",
                signature="s",
                body=[query],
            ))
            matches = reply.body[0] if reply.body else []
        except Exception:
            logger.exception(f"Failed to query WindowsRunner for '{query}'")
            return []

        uuids = []
        for match in matches:
            m = _UUID_RE.search(match[0])
            if m:
                uuids.append("{" + m.group(1) + "}")
        return uuids

    async def _has_fullscreen_window(self, who: str) -> bool | None:
        """Check if the app identified by 'who' has a fullscreen window.

        Returns True if a fullscreen window is found, False if windows were
        found but none are fullscreen, or None if no windows matched (unknown).
        """
        uuids = await self._query_windows(who)
        if not uuids:
            return None

        for uuid in uuids:
            if await self._is_window_fullscreen(uuid):
                logger.debug(f"Fullscreen window found for '{who}'")
                return True
        return False

    async def _any_fullscreen_window(self) -> bool:
        """Check if any window on the desktop is fullscreen."""
        uuids = await self._query_windows("")
        seen = set()
        for uuid in uuids:
            if uuid in seen:
                continue
            seen.add(uuid)
            if await self._is_window_fullscreen(uuid):
                logger.debug(f"Fullscreen window found: {uuid}")
                return True
        return False

    async def _should_suppress(self) -> bool:
        """Check if an app with a non-audio inhibition has a fullscreen window."""
        if not self._policy_agent_props:
            logger.debug("PolicyAgent not connected, suppressing as safety fallback")
            return True

        # Read ActiveInhibitions: a(ssssu) = (what, who, why, mode, cookie)
        try:
            raw = await self._policy_agent_props.call_get(
                POLICY_AGENT_IFACE, "ActiveInhibitions"
            )
            inhibitions = raw.value if hasattr(raw, "value") else raw
        except Exception:
            logger.exception("Failed to read ActiveInhibitions, suppressing")
            return True

        # Filter out audio-only inhibitions
        relevant = []
        for entry in inhibitions:
            what, who, why, mode, cookie = entry
            if _is_audio_only(why):
                logger.debug(f"Ignoring audio-only inhibition: who={who} why={why}")
                continue
            relevant.append((what, who, why, mode, cookie))

        if not relevant:
            return False

        if not self._kwin_available:
            logger.debug("KWin not available, suppressing as safety fallback")
            return True

        # Check if any inhibiting app has a fullscreen window
        unmatched = False
        for what, who, why, mode, cookie in relevant:
            result = await self._has_fullscreen_window(who)
            if result is True:
                return True
            if result is None:
                # No window matched the inhibitor name (e.g. Proton/XWayland
                # games report as "SDL Application").
                logger.debug(f"No window found for inhibitor '{who}' (reason: {why})")
                unmatched = True

        if unmatched:
            # Inhibitor name didn't match any window title — fall back to
            # checking whether *any* window is fullscreen.
            if await self._any_fullscreen_window():
                logger.debug("Unmatched inhibitor with a fullscreen window present, suppressing")
                return True

        logger.debug("No fullscreen window for inhibiting apps, allowing idle")
        return False

    async def _on_inhibitions_changed(self, iface_name, changed, invalidated):
        """Handle PolicyAgent property changes while in SUPPRESSED state."""
        if self._state != State.SUPPRESSED:
            return

        needs_check = "ActiveInhibitions" in changed or "ActiveInhibitions" in invalidated
        if not needs_check:
            return

        logger.debug("ActiveInhibitions changed while SUPPRESSED, re-evaluating")
        try:
            if not await self._should_suppress():
                logger.info("No longer suppressed, resetting idle timer")
                self._state = State.ACTIVE
                self._wayland_mgr.reset()
        except Exception:
            logger.exception("Error re-evaluating suppression")

    async def connect(self):
        self._message_bus = await MessageBus().connect()

        # Connect to PolicyAgent
        try:
            intro = await self._message_bus.introspect(
                POLICY_AGENT_BUS_NAME, POLICY_AGENT_PATH
            )
            proxy = self._message_bus.get_proxy_object(
                POLICY_AGENT_BUS_NAME, POLICY_AGENT_PATH, intro
            )
            self._policy_agent_props = proxy.get_interface(DBUS_PROPERTIES_IFACE)
            self._policy_agent_props.on_properties_changed(
                self._on_inhibitions_changed
            )
            logger.debug("Connected to PolicyAgent")
        except Exception:
            logger.exception("Failed to connect to PolicyAgent")
            self._policy_agent_props = None

        # Connect to KWin (for getWindowInfo)
        try:
            intro = await self._message_bus.introspect(KWIN_BUS_NAME, KWIN_PATH)
            proxy = self._message_bus.get_proxy_object(
                KWIN_BUS_NAME, KWIN_PATH, intro
            )
            self._kwin_iface = proxy.get_interface(KWIN_IFACE)
            self._kwin_available = True
            logger.debug("Connected to KWin")
        except Exception:
            logger.exception("Failed to connect to KWin")
            self._kwin_available = False

    async def disconnect(self):
        if self._policy_agent_props:
            try:
                self._policy_agent_props.off_properties_changed(
                    self._on_inhibitions_changed
                )
            except Exception:
                pass
        if self._message_bus:
            try:
                self._message_bus.disconnect()
                await self._message_bus.wait_for_disconnect()
            except Exception:
                pass
        logger.debug("Disconnected from DBus")

    async def run(self):
        delay = 1
        max_delay = 30
        while True:
            try:
                await self.connect()
                delay = 1
                await self._message_bus.wait_for_disconnect()
            except asyncio.CancelledError:
                await self.disconnect()
                raise
            except Exception:
                logger.exception("DBus disconnected")
                await self.disconnect()
                await asyncio.sleep(delay)
                delay = min(delay * 2, max_delay)
