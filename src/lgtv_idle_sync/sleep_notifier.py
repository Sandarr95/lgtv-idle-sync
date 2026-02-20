import asyncio
import logging
import os
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
        self._inhibit_fd = None
        self._transition_lock = asyncio.Lock()

    async def _take_inhibit_lock(self):
        if self._inhibit_fd is not None:
            return
        try:
            self._inhibit_fd = await self._login1_manager_interface.call_inhibit(
                "sleep:shutdown", "lgtv-idle-sync", "Ensure TV is off before sleep", "delay"
            )
            logger.debug(f"Inhibit lock taken (fd: {self._inhibit_fd})")
        except Exception:
            logger.exception("Failed to take inhibit lock")

    def _release_inhibit_lock(self):
        if self._inhibit_fd is not None:
            try:
                os.close(self._inhibit_fd)
                logger.debug(f"Inhibit lock released (fd: {self._inhibit_fd})")
            except Exception:
                logger.exception("Failed to release inhibit lock")
            self._inhibit_fd = None

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
        self._login1_manager_interface = _login1.get_interface(LOGIN1_DBUS_INTERFACE)
        self._login1_manager_interface.on_prepare_for_sleep(
            self.on_prepare_for_sleep_or_shutdown
        )
        self._login1_manager_interface.on_prepare_for_shutdown(
            self.on_prepare_for_sleep_or_shutdown
        )
        async with self._transition_lock:
            await self._take_inhibit_lock()
        logger.debug("Connected to logind and took inhibit lock")

    async def disconnect(self):
        async with self._transition_lock:
            self._release_inhibit_lock()
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
        async with self._transition_lock:
            if sleeping:
                logger.info("System preparing to sleep → powering off")
                try:
                    await self._power_off_fn()
                except asyncio.CancelledError:
                    logger.info("Power off command cancelled (system resumed?)")
                except Exception:
                    logger.exception("Power off command failed during sleep preparation")
                finally:
                    # Always release if we are still intending to sleep
                    # If we were cancelled by a power_on, it doesn't matter much
                    # as we'll re-take it in the other branch if it runs.
                    self._release_inhibit_lock()
            else:
                logger.info("System resumed from sleep → powering on")
                await self._take_inhibit_lock()
                try:
                    await self._power_on_fn()
                except asyncio.CancelledError:
                    logger.debug("Power on command cancelled")
                except Exception:
                    logger.exception("Power on command failed during resume")
