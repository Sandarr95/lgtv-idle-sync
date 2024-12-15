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
