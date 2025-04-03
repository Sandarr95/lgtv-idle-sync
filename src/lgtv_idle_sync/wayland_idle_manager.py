import asyncio
import logging

from pywayland.client import Display
from pywayland.protocol.ext_idle_notify_v1 import ext_idle_notifier_v1
from pywayland.protocol.wayland import WlSeat

from lgtv_idle_sync.interface import IdleManager

logger = logging.getLogger(__name__)

def default_idled():
    logger.debug("Default idle handler")

def default_resumed():
    logger.debug("Default resume handler")

class WaylandIdleManager(IdleManager):
    def __init__(self, idle_timeout_secs=5, idle_fn=default_idled, resume_fn=default_resumed):
        super().__init__()
        self._idle_timeout_ms = idle_timeout_secs * 1000
        self._idle_fn = idle_fn
        self._resume_fn = resume_fn
        self._idle_notification = None
        self._old_idle_notifications = []

        # Connect to the Wayland display
        self._display = Display()
        self._display.connect()  # Explicitly connect to the Wayland display
        self._fd = self._display.get_fd()
        self._wayland_registry = self._display.get_registry()

        # Register Wayland global objects
        self._wayland_registry.dispatcher["global"] = self._global_handler
        self._display.roundtrip()

        # Ensure idle_notifier is available
        if not hasattr(self, "_idle_notifier"):
            raise RuntimeError("ext_idle_notifier_v1 is not supported by the compositor!")
        if not hasattr(self, "_seat"):
            raise RuntimeError("wl_seat is not available in the compositor!")

        self._register_idle_notification()

    def __del__(self):
        self._deregister_idle_notification()
        self._seat.release()
        self._idle_notifier.destroy()
        self._display.disconnect()
        self._wayland_registry.destroy()

    def _global_handler(self, registry, name, interface, version):
        """Handle registry events and bind to ext_idle_notifier_v1"""
        if interface == "ext_idle_notifier_v1":
            logger.debug("Binding ext_idle_notifier_v1")
            self._idle_notifier = registry.bind(name, ext_idle_notifier_v1.ExtIdleNotifierV1, version)
        elif interface == "wl_seat":
            logger.debug("Binding wl_seat")
            self._seat = registry.bind(name, WlSeat, version)

    def reset(self):
        """Reset idle_notification for out of band change"""
        logger.debug("Resetting idle notification")
        self._mark_delete_for_idle_notification()
        self._register_idle_notification()

    def _register_idle_notification(self):
        if not self._idle_notification:
            logger.debug("Registering idle notification")
            self._idle_notification = self._idle_notifier.get_idle_notification(
                self._idle_timeout_ms,
                self._seat
            )
            self._idle_notification.dispatcher["idled"] = self.idled
            self._idle_notification.dispatcher["resumed"] = self.resumed
            self._display.flush()

    def _deregister_idle_notification(self):
        if self._idle_notification:
            logger.debug("Deregistering idle notification")
            self._idle_notification.destroy()
            self._idle_notification = None
        self._delete_marked_idle_notifications()

    def _mark_delete_for_idle_notification(self):
        if self._idle_notification:
            self._old_idle_notifications.append(self._idle_notification)
            self._idle_notification = None

    def _delete_marked_idle_notifications(self):
        for idle_notification in self._old_idle_notifications:
            idle_notification.destroy()
        self._old_idle_notifications = []

    def _on_resume(self):
        self._delete_marked_idle_notifications()
        self._resume_fn()
        if self._has_inhibitor():
            self._deregister_idle_notification()

    def _on_idle(self):
        self._idle_fn()

    def _on_inhibit(self):
        self._deregister_idle_notification()
        self._resume_fn()

    def _on_uninhibit(self):
        self._register_idle_notification()

    async def wait_readable(self):
        loop = asyncio.get_running_loop()
        event = asyncio.Event()
        try:
            loop.add_reader(self._fd, lambda: event.set())
            await event.wait()
        finally:
            loop.remove_reader(self._fd)

    async def run(self):
        try:
            while(True):
                await self.wait_readable()
                self._display.dispatch(block=True)
                # TODO: detect `self.fd` becoming unreadable, reconnect:
                # Use inotify `$XDG_RUNTIME_DIR/$WAYLAND_DISPLAY` (or "wayland-0")
        except asyncio.exceptions.CancelledError:
            raise
