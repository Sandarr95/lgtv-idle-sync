#!/usr/bin/env python3
import asyncio
from lgtv_idle_sync import idle_monitor, lgtv_idle_client

async def main():
    try:
        loop = asyncio.get_running_loop()
        notifier = idle_monitor.IdleNotifier(
            idled=lgtv_idle_client.idle,
            resumed=lgtv_idle_client.resume
        )

        loop.add_reader(notifier.fd, notifier.run)
        print("Waiting")
        await asyncio.Event().wait()
    except asyncio.exceptions.CancelledError:
        print("Exiting")
        loop.remove_reader(notifier.fd)

if __name__ == "__main__":
    asyncio.run(main())
