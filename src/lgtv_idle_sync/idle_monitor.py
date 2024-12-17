from pywayland.client import Display
from pywayland.protocol.ext_idle_notify_v1 import ext_idle_notifier_v1
from pywayland.protocol.wayland import WlSeat
from signal import SIGINT, SIGTERM, signal
import time

class IdleNotifier:
    def __init__(self):
        # Connect to the Wayland display
        self.display = Display()
        self.display.connect()  # Explicitly connect to the Wayland display
        self.fd = self.display.get_fd()
        self.registry = self.display.get_registry()

        # Register Wayland global objects
        self.registry.dispatcher["global"] = self.global_handler
        self.display.roundtrip()

        # Ensure idle_notifier is available
        if not hasattr(self, "idle_notifier"):
            raise RuntimeError("ext_idle_notifier_v1 is not supported by the compositor!")
        if not hasattr(self, "seat"):
            raise RuntimeError("wl_seat is not available in the compositor!")

        # Create an idle timeout object (e.g., 5 seconds)
        self.idle_notification = self.idle_notifier.get_idle_notification(5000, self.seat)
        # Attach listeners for idle and resume events
        self.idle_notification.dispatcher["idled"] = self.idled
        self.idle_notification.dispatcher["resumed"] = self.resumed

        self.display.flush()

    def __del__(self):
        self.idle_notification.destroy()
        self.seat.release()
        self.idle_notifier.destroy()
        self.display.disconnect()
        self.registry.destroy()

    def global_handler(self, registry, name, interface, version):
        """Handle registry events and bind to ext_idle_notifier_v1"""
        if interface == "ext_idle_notifier_v1":
            self.idle_notifier = registry.bind(name, ext_idle_notifier_v1.ExtIdleNotifierV1, version)
        elif interface == "zwp_idle_inhibit_manager_v1":
            print("TODO: listen to ", interface)
        elif interface == "wl_seat":
            self.seat = registry.bind(name, WlSeat, version)

    def idled(self, idle_notification, *args):
        """Handle idle event"""
        print("Seat is idle", time.time())

    def resumed(self, idle_notification, *args):
        """Handle resume event"""
        print("Seat is active", time.time())

    def run(self):
        self.display.dispatch(block=True)
