import asyncio
import logging
from importlib import resources
from dbus_fast.aio import MessageBus
from dbus_fast.errors import DBusError

from lgtv_idle_sync.interface import Inhibitor

logger = logging.getLogger(__name__)

POWER_MANAGEMENT_DBUS_BUS_NAME = 'org.freedesktop.PowerManagement.Inhibit'
POWER_MANAGEMENT_DBUS_PATH = '/org/freedesktop/PowerManagement/Inhibit'
POWER_MANAGEMENT_DBUS_INTERFACE = 'org.freedesktop.PowerManagement.Inhibit'

class PowerManagementIdleInhibitor(Inhibitor):

    def __init__(self, idle_manager):
        super().__init__(idle_manager)
        self._message_bus = None
        self._power_management_interface = None

    async def connect(self):
        self._message_bus = await MessageBus().connect()
        _introspection = await self._message_bus.introspect(
            POWER_MANAGEMENT_DBUS_NAME,
            POWER_MANAGEMENT_DBUS_PATH
        )
        _power_management = self._message_bus.get_proxy_object(
            POWER_MANAGEMENT_DBUS_BUS_NAME,
            POWER_MANAGEMENT_DBUS_PATH,
            _introspection
        )
        self._power_management_interface = _power_management.get_interface(
            POWER_MANAGEMENT_DBUS_INTERFACE
        )
        self._power_management_interface.on_has_inhibit_changed(self._on_has_inhibit_changed)
        await self._on_has_inhibit_changed(await self._power_management_interface.call_has_inhibit())

    async def disconnect(self):
        if self._power_management_interface:
            self._power_management_interface.off_has_inhibit_changed(
                self.on_has_inhibit_changed
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

    async def _on_has_inhibit_changed(self, has_inhibit):
        if has_inhibit:
            self.inhibit()
        else:
            self.uninhibit()
