import asyncio
import logging
from dbus_fast.aio import MessageBus
from dbus_fast import BusType

logger = logging.getLogger(__name__)

LOGIN1_DBUS_NAME = "org.freedesktop.login1"
LOGIN1_DBUS_PATH = "/org/freedesktop/login1"
LOGIN1_DBUS_INTERFACE = "org.freedesktop.login1.Manager"

NM_DBUS_NAME = "org.freedesktop.NetworkManager"
NM_DBUS_PATH = "/org/freedesktop/NetworkManager"
NM_STATE_CONNECTED_GLOBAL = 70

class SleepNotifier:

    def __init__(self, power_off_fn, power_on_fn, sleep_state_fn=None):
        self._power_off_fn = power_off_fn
        self._power_on_fn = power_on_fn
        self._sleep_state_fn = sleep_state_fn
        self._message_bus = None
        self._login1_manager_interface = None
        self._nm_props = None
        self._inhibit_proc = None
        self._transition_lock = asyncio.Lock()

    async def _take_inhibit_lock(self):
        if self._inhibit_proc is not None:
            return
        try:
            # Use systemd-inhibit subprocess because dbus-fast cannot
            # receive Unix file descriptors from the Inhibit method.
            self._inhibit_proc = await asyncio.create_subprocess_exec(
                "systemd-inhibit",
                "--what=sleep:shutdown",
                "--who=lgtv-idle-sync",
                "--why=Ensure TV is off before sleep",
                "--mode=delay",
                "sleep", "infinity",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            logger.debug(f"Inhibit lock taken (pid: {self._inhibit_proc.pid})")
        except Exception:
            logger.exception("Failed to take inhibit lock")

    async def _release_inhibit_lock(self):
        if self._inhibit_proc is not None:
            try:
                self._inhibit_proc.terminate()
                await self._inhibit_proc.wait()
                logger.debug("Inhibit lock released")
            except ProcessLookupError:
                logger.debug("Inhibit process already terminated")
            except Exception:
                logger.exception("Failed to release inhibit lock")
            self._inhibit_proc = None

    async def _wait_for_network(self, timeout=30):
        """Wait for NetworkManager to reach CONNECTED_GLOBAL."""
        if not self._nm_props:
            logger.debug("NetworkManager not connected, skipping wait")
            return

        try:
            state = await self._nm_props.call_get(NM_DBUS_NAME, "State")
            state_val = state.value if hasattr(state, "value") else state
            if state_val >= NM_STATE_CONNECTED_GLOBAL:
                logger.debug("Network already connected")
                return

            logger.debug(f"Waiting for network (current state: {state_val})")
            ready = asyncio.Event()

            def on_props_changed(iface_name, changed, invalidated):
                if "State" in changed:
                    val = changed["State"]
                    val = val.value if hasattr(val, "value") else val
                    if val >= NM_STATE_CONNECTED_GLOBAL:
                        ready.set()

            self._nm_props.on_properties_changed(on_props_changed)
            try:
                await asyncio.wait_for(ready.wait(), timeout=timeout)
                logger.debug("Network connected")
            except asyncio.TimeoutError:
                logger.warning(f"Network did not come up within {timeout}s")
            finally:
                try:
                    self._nm_props.off_properties_changed(on_props_changed)
                except Exception:
                    pass
        except Exception:
            logger.exception("Error waiting for network")

    async def connect(self):
        self._message_bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
        _introspection = await self._message_bus.introspect(
            LOGIN1_DBUS_NAME,
            LOGIN1_DBUS_PATH
        )
        _login1 = self._message_bus.get_proxy_object(
            LOGIN1_DBUS_NAME,
            LOGIN1_DBUS_PATH,
            _introspection,
        )
        self._login1_manager_interface = _login1.get_interface(LOGIN1_DBUS_INTERFACE)
        self._login1_manager_interface.on_prepare_for_sleep(
            self.on_prepare_for_sleep_or_shutdown
        )
        self._login1_manager_interface.on_prepare_for_shutdown(
            self.on_prepare_for_sleep_or_shutdown
        )

        # Connect to NetworkManager for post-resume waiting
        try:
            nm_intro = await self._message_bus.introspect(NM_DBUS_NAME, NM_DBUS_PATH)
            nm_proxy = self._message_bus.get_proxy_object(
                NM_DBUS_NAME, NM_DBUS_PATH, nm_intro
            )
            self._nm_props = nm_proxy.get_interface(
                "org.freedesktop.DBus.Properties"
            )
            logger.debug("Connected to NetworkManager")
        except Exception:
            logger.exception("Failed to connect to NetworkManager")
            self._nm_props = None

        async with self._transition_lock:
            await self._take_inhibit_lock()
        logger.debug("Connected to logind and took inhibit lock")

    async def disconnect(self):
        async with self._transition_lock:
            await self._release_inhibit_lock()
        if self._login1_manager_interface:
            try:
                self._login1_manager_interface.off_prepare_for_sleep(
                    self.on_prepare_for_sleep_or_shutdown
                )
                self._login1_manager_interface.off_prepare_for_shutdown(
                    self.on_prepare_for_sleep_or_shutdown
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

    async def on_prepare_for_sleep_or_shutdown(self, sleeping: bool):
        async with self._transition_lock:
            if sleeping:
                if self._sleep_state_fn:
                    self._sleep_state_fn(True)
                logger.info("System preparing to sleep → powering off")
                try:
                    await asyncio.to_thread(self._power_off_fn)
                except asyncio.CancelledError:
                    logger.info("Power off command cancelled (system resumed?)")
                except Exception:
                    logger.exception("Power off command failed during sleep preparation")
                finally:
                    await self._release_inhibit_lock()
            else:
                logger.info("System resumed from sleep → powering on")
                await self._take_inhibit_lock()
                await self._wait_for_network()
                try:
                    await asyncio.to_thread(self._power_on_fn)
                except asyncio.CancelledError:
                    logger.debug("Power on command cancelled")
                except Exception:
                    logger.exception("Power on command failed during resume")
                if self._sleep_state_fn:
                    self._sleep_state_fn(False)
