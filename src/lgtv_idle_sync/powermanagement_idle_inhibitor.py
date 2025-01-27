from importlib import resources
from dbus_fast.aio import MessageBus
from dbus_fast.errors import DBusError

import lgtv_idle_sync.resources.dbus

class PowerManagementIdleInhibitor:

    _dbus_resource = 'org.freedesktop.PowerManagement.Inhibit.xml'
    _dbus_bus_name = 'org.freedesktop.PowerManagement.Inhibit'
    _dbus_path = '/org/freedesktop/PowerManagement/Inhibit'
    _dbus_interface = 'org.freedesktop.PowerManagement.Inhibit'

    def __init__(self, idle_notifier):
        self._idle_notifier = idle_notifier
        self._inhibitor = None

    async def connect(self):
        self._message_bus = await MessageBus().connect()
        self._introspection = resources.read_text(
            lgtv_idle_sync.resources.dbus,
            PowerManagementIdleInhibitor._dbus_resource
        )
        self._power_management = self._message_bus.get_proxy_object(
            PowerManagementIdleInhibitor._dbus_bus_name,
            PowerManagementIdleInhibitor._dbus_path,
            self._introspection
        )
        self._policy_agent = self._power_management.get_interface(
            PowerManagementIdleInhibitor._dbus_interface
        )

        self._policy_agent.on_has_inhibit_changed(self.on_has_inhibit_changed)
        try:
          await self.on_has_inhibit_changed(await self._policy_agent.call_has_inhibit())
        except DBusError:
          pass
        return self

    async def on_has_inhibit_changed(self, has_inhibit):
        match (has_inhibit, self._inhibitor is None):
            case (True, True):
                self._inhibitor = self._idle_notifier.register_inhibitor()
            case (False, False):
                self._inhibitor.destroy()
                self._inhibitor = None
