#!/usr/bin/env python3
import asyncio
from lgtv_idle_sync import idle_monitor, lgtv_idle_client

async def main():
    try:
        loop = asyncio.get_running_loop()
        notifier = idle_monitor.IdleNotifier()

        tasks = [
            asyncio.create_task(notifier.run())
        ]
        print("Started")
        await asyncio.Event().wait()
    except asyncio.exceptions.CancelledError:
        print("Exiting")

if __name__ == "__main__":
    asyncio.run(main())
