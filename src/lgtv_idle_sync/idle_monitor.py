from pywayland.client import Display
from pywayland.protocol.ext_idle_notify_v1 import ext_idle_notifier_v1
from pywayland.protocol.wayland import WlSeat
from signal import SIGINT, SIGTERM, signal

class IdleNotifier:
    def __init__(self):
        # Connect to the Wayland display
        self.display = Display()
        self.display.connect()  # Explicitly connect to the Wayland display
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
        self.idle_notification = self.idle_notifier.get_idle_notification(10000, self.seat)
        # Attach listeners for idle and resume events
        self.idle_notification.dispatcher["idled"] = self.idled
        self.idle_notification.dispatcher["resumed"] = self.resumed
        # self.display.roundtrip()
        print("ext_idle_notifier_v1 setup complete")

    def global_handler(self, registry, name, interface, version):
        """Handle registry events and bind to ext_idle_notifier_v1"""
        print("handle interface: ", interface)
        if interface == "ext_idle_notifier_v1":
            self.idle_notifier = registry.bind(name, ext_idle_notifier_v1.ExtIdleNotifierV1, version)
        elif interface == "wl_seat":
            self.seat = registry.bind(name, WlSeat, version)

    def idled(self, idle_notification, *args):
        """Handle idle event"""
        print("Seat is idle")

    def resumed(self, idle_notification, *args):
        """Handle resume event"""
        print("Seat is active")

    def run(self):
        """Main loop to handle Wayland events"""
        while True:
            self.display.dispatch(block=True)

if __name__ == "__main__":
    notifier = IdleNotifier()
    print("Run ext_idle_notifier_v1 listener")
    signal(SIGINT, lambda _, __: notifier.destroy())
    signal(SIGTERM, lambda _, __: notifier.destroy())
    notifier.run()


from PyQt6.QtCore import QCoreApplication
from PyQt6.QtDBus import QDBusConnection, QDBusInterface
import signal

def get_kidletime_interface():
    bus = QDBusConnection.sessionBus()
    kidletime = QDBusInterface("org.kde.kidletime", "/org/kde/kidletime", "org.kde.kidletime", bus)
    if not kidletime.isValid():
        print("Could not connect to org.kde.kidletime!")
        return None
    return kidletime

def get_screensaver_interface():
    bus = QDBusConnection.sessionBus()
    screensaver = QDBusInterface("org.freedesktop.ScreenSaver", "/ScreenSaver", "org.freedesktop.ScreenSaver", bus)
    if not screensaver.isValid():
        print("Could not connect to org.freedesktop.ScreenSaver!")
        return None
    return screensaver

def is_screensaver_inhibited(screensaver_interface):
    if screensaver_interface:
        reply = screensaver_interface.call("GetInhibitors")
        if reply.isValid():
            return bool(reply.arguments()[0])
    return False

def handle_timeout_reached(timeout_id, state, idle_function):
    if timeout_id == state['timeout_id'] and not state['timeout_triggered']:
        if not is_screensaver_inhibited(state['screensaver_interface']):
            print(f"Idle timeout reached for unique ID: {timeout_id}")
            state['timeout_triggered'] = True
            idle_function()
        else:
            print("Screensaver is inhibited. Idle action skipped.")

def handle_activity_resumed(state, resume_function):
    if state['timeout_triggered']:
        print("Activity resumed after idle timeout.")
        state['timeout_triggered'] = False
        resume_function()

def cleanup_on_exit(signum, frame, state):
    if state['timeout_id'] is not None and state['kidletime_interface']:
        reply = state['kidletime_interface'].call("removeIdleTimeout", state['timeout_id'])
        if reply.isValid():
            print(f"Removed idle timeout with ID: {state['timeout_id']}")
        else:
            print("Failed to remove idle timeout!")
    else:
        print("No timeout ID to remove.")
    print("Exiting application.")
    state['app'].quit()

def start_monitoring(idle_function, resume_function):
    app = QCoreApplication([])

    kidletime_interface = get_kidletime_interface()
    screensaver_interface = get_screensaver_interface()

    if not kidletime_interface:
        print("KIdleTime is not available. Exiting...")
        return

    state = {
        'app': app,
        'kidletime_interface': kidletime_interface,
        'screensaver_interface': screensaver_interface,
        'timeout_triggered': False,
        'idle_timeout_ms': 60000,
        'timeout_id': None
    }

    reply = kidletime_interface.call("addIdleTimeout", state['idle_timeout_ms'])
    if reply.isValid():
        state['timeout_id'] = reply.arguments()[0]
        print(f"Registered idle timeout with ID: {state['timeout_id']}")
    else:
        print("Failed to register idle timeout!")
        return

    QDBusConnection.sessionBus().connect(
        "org.kde.kidletime",
        "/org/kde/kidletime",
        "org.kde.kidletime",
        "timeoutReached",
        lambda timeout_id: handle_timeout_reached(timeout_id, state, idle_function)
    )

    QDBusConnection.sessionBus().connect(
        "org.kde.kidletime",
        "/org/kde/kidletime",
        "org.kde.kidletime",
        "resumedActivity",
        lambda: handle_activity_resumed(state, resume_function)
    )

    signal.signal(signal.SIGINT, lambda signum, frame: cleanup_on_exit(signum, frame, state))
    signal.signal(signal.SIGTERM, lambda signum, frame: cleanup_on_exit(signum, frame, state))

    print("Starting event-driven idle monitoring...")
    app.exec_()
