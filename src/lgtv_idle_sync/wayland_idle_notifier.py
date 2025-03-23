import asyncio
import logging
import weakref

from pywayland.client import Display
from pywayland.protocol.ext_idle_notify_v1 import ext_idle_notifier_v1
from pywayland.protocol.wayland import WlSeat

logger = logging.getLogger(__name__)

async def wait_readable(fd):
    loop = asyncio.get_running_loop()
    event = asyncio.Event()
    try:
        loop.add_reader(fd, lambda: event.set())
        await event.wait()
    finally:
        loop.remove_reader(fd)

def default_idled():
    """Handle idle event"""
    logger.debug("Seat is idle")

def default_resumed():
    """Handle resume event"""
    logger.debug("Seat is active")

class Inhibitor:
    def __init__(self, idle_notifier):
        self._idle_notifier = weakref.ref(idle_notifier)
        self._finalizer = weakref.finalize(self, self.destroy)

    def destroy(self):
        idle_notifier = self._idle_notifier()
        if idle_notifier:
            idle_notifier.deregister_inhibitor(self)

class WaylandIdleNotifier:
    def __init__(self, idle_timeout_secs=5, idle_fn=default_idled, resume_fn=default_resumed):
        self._can_run_idle = True;
        self._can_run_resume = False;
        self.idle_timeout_ms = idle_timeout_secs * 1000
        self.idle_fn = idle_fn
        self.resume_fn = resume_fn
        self._inhibitors = weakref.WeakSet()
        self.idle_notification = None

        # Connect to the Wayland display
        self.display = Display()
        self.display.connect()  # Explicitly connect to the Wayland display
        self.fd = self.display.get_fd()
        self.wayland_registry = self.display.get_registry()

        # Register Wayland global objects
        self.wayland_registry.dispatcher["global"] = self.global_handler
        self.display.roundtrip()

        # Ensure idle_notifier is available
        if not hasattr(self, "idle_notifier"):
            raise RuntimeError("ext_idle_notifier_v1 is not supported by the compositor!")
        if not hasattr(self, "seat"):
            raise RuntimeError("wl_seat is not available in the compositor!")

        self.register_idle_notifier()

    def __del__(self):
        self.deregister_idle_notifier()
        self.seat.release()
        self.idle_notifier.destroy()
        self.display.disconnect()
        self.wayland_registry.destroy()

    def global_handler(self, registry, name, interface, version):
        """Handle registry events and bind to ext_idle_notifier_v1"""
        if interface == "ext_idle_notifier_v1":
            logger.debug("Binding ext_idle_notifier_v1")
            self.idle_notifier = registry.bind(name, ext_idle_notifier_v1.ExtIdleNotifierV1, version)
        elif interface == "wl_seat":
            logger.debug("Binding wl_seat")
            self.seat = registry.bind(name, WlSeat, version)

    def idled(self, idle_notification, *args):
        if self._can_run_idle:
            logger.debug("Idling")
            self.idle_fn()
            self._can_run_idle = False
            self._can_run_resume = True

    def resumed(self, idle_notification, *args):
        if self._can_run_resume:
            logger.debug("Resuming")
            self.resume_fn()
            self._can_run_idle = True
            self._can_run_resume = False
            if len(self._inhibitors) > 0:
                self.deregister_idle_notifier()

    def register_idle_notifier(self):
        if not self.idle_notification and len(self._inhibitors) == 0:
            logger.debug("Registering idle notifications")
            self.idle_notification = self.idle_notifier.get_idle_notification(
                self.idle_timeout_ms,
                self.seat
            )
            self.idle_notification.dispatcher["idled"] = self.idled
            self.idle_notification.dispatcher["resumed"] = self.resumed
            self.display.flush()

    def deregister_idle_notifier(self):
        if self._can_run_idle and self.idle_notification and len(self._inhibitors) == 0:
            logger.debug("Deregistering idle notifications")
            self.idle_notification.destroy()
            self.idle_notification = None

    def register_inhibitor(self):
        logger.debug("Registering inhibitor")
        inhibitor = Inhibitor(self)
        self._inhibitors.add(inhibitor)
        self.deregister_idle_notifier()
        return inhibitor

    def deregister_inhibitor(self, inhibitor):
        logger.debug("Deregistering inhibitor")
        self._inhibitors.discard(inhibitor)
        self.register_idle_notifier()

    def reset_idling(self):
        if not self._can_run_idle:
            logger.debug("Reset idling state")
            self._can_run_idle = True
            self.deregister_idle_notifier()
            self.register_idle_notifier()

    async def run(self):
        try:
            while(True):
                await wait_readable(self.fd)
                self.display.dispatch(block=True)
        except asyncio.exceptions.CancelledError:
            raise
