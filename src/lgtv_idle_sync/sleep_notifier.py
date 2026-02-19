import asyncio
import logging
from importlib import resources
from dbus_fast.aio import MessageBus
from dbus_fast.errors import DBusError

logger = logging.getLogger(__name__)

LOGIN1_DBUS_NAME = "org.freedesktop.login1"
LOGIN1_DBUS_PATH = "/org/freedesktop/login1"
LOGIN1_DBUS_INTERFACE = "org.freedesktop.login1.Manager"

class SleepNotifier:

    def __init__(self, power_off_fn, power_on_fn):
        self._power_off_fn = power_off_fn
        self._power_on_fn = power_on_fn
        self._message_bus = None
        self._login1_manager_interface = None

    async def connect(self):
        self._message_bus = await MessageBus().connect()
        _introspection = await self._message_bus.introspect(
            LOGIN1_DBUS_NAME,
            LOGIN1_DBUS_PATH
        )
        _login1 = self._message_bus.get_proxy_object(
            LOGIN1_DBUS_NAME,
            LOGIN1_DBUS_PATH,
            _introspection,
        )
        self._login1_manager_interface = proxy.get_interface(LOGIN1_DBUS_INTERFACE)
        self._login1_manager_interface.on_prepare_for_sleep(
            self.on_prepare_for_sleep_or_shutdown
        )
        self._login1_manager_interface.on_prepare_for_shutdown(
            self.on_prepare_for_sleep_or_shutdown
        )
        logger.debug("Connected to logind PrepareForSleep signal")

    async def disconnect(self):
        if self._login1_manager_interface:
            self._login1_manager_interface.off_prepare_for_sleep(
                self.on_prepare_for_sleep_or_shutdown
            )
            self._login1_manager_interface.off_prepare_for_shutdown(
                self.on_prepare_for_sleep_or_shutdown
            )
        if self._message_bus:
            self._message_bus.disconnect()
            await self._message_bus.wait_for_disconnect()
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
        if sleeping:
            logger.info("System preparing to sleep → powering off")
            await self._power_off_fn()
        else:
            logger.info("System resumed from sleep → powering on")
            await self._power_on_fn()
