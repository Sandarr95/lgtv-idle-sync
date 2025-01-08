#!/usr/bin/env python3
import asyncio
from dbus_fast.aio import MessageBus
from lgtv_idle_sync.wayland_idle_notifier import WaylandIdleNotifier
from lgtv_idle_sync.powermanagement_idle_notifier import PowerManagementIdleNotifier
from lgtv_idle_sync import lgtv_idle_client

async def main():
    try:
        loop = asyncio.get_running_loop()
        notifier = idle_monitor.WaylandIdleNotifier(
            idle_timeout_secs=300,
            idled=lgtv_idle_client.idle,
            resumed=lgtv_idle_client.resume
        )

        tasks = [
            asyncio.create_task(notifier.run())
        ]
        pwr_management_notifier = await PowerManagementIdleNotifier().connect()
        print("Started")
        await asyncio.Event().wait()
    except asyncio.exceptions.CancelledError:
        print("Exiting")

if __name__ == "__main__":
    asyncio.run(main())
