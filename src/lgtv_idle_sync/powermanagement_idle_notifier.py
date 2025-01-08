from dbus_fast.aio import MessageBus

class PowerManagementIdleNotifier:

    _dbus_bus_name = 'org.freedesktop.PowerManagement.Inhibit'
    _dbus_path = '/org/freedesktop/PowerManagement/Inhibit'
    _dbus_interface = 'org.freedesktop.PowerManagement.Inhibit'

    def __init__(self, on_idle=None, on_resume=None):
        self._on_idle = on_idle
        self._on_resume = on_resume

    async def connect(self):
        self._message_bus = await MessageBus().connect()
        # TODO: Only use dynamic introspection for dev, use static file otherwise
        self._introspection = await self._message_bus.introspect(
            PowerManagementIdleNotifier._dbus_bus_name,
            PowerManagementIdleNotifier._dbus_path
        )
        self._power_management = self._message_bus.get_proxy_object(
            PowerManagementIdleNotifier._dbus_bus_name,
            PowerManagementIdleNotifier._dbus_path,
            self._introspection
        )
        self._policy_agent = self._power_management.get_interface(
            PowerManagementIdleNotifier._dbus_interface
        )

        self._policy_agent.on_has_inhibit_changed(self.on_has_inhibit_changed)
        return self

    async def on_has_inhibit_changed(self, changed_properties):
        print(self, changed_properties)
