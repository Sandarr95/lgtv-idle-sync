#!/usr/bin/env python3
import asyncio
from lgtv_idle_sync.wayland_idle_notifier import WaylandIdleNotifier
from lgtv_idle_sync.powermanagement_idle_inhibitor import PowerManagementIdleInhibitor
from lgtv_idle_sync.pulseaudio_notifier import PulseAudioNotifier
from lgtv_idle_sync import lgtv_idle_client

async def main():
    try:
        loop = asyncio.get_running_loop()
        wayland_idle_notifier = WaylandIdleNotifier(
            idle_timeout_secs=180,
            idle_fn=lgtv_idle_client.idle,
            resume_fn=lgtv_idle_client.resume
        )

        def resume_audio():
            lgtv_idle_client.resume_audio()
            wayland_idle_notifier.reset_idling()

        pulseaudio_notifier = PulseAudioNotifier(
            resume_audio=resume_audio,
            min_secs_between_requests=120
        )

        tasks = [
            asyncio.create_task(wayland_idle_notifier.run()),
            asyncio.create_task(pulseaudio_notifier.run())
        ]
        pwr_management_inhibitor = await PowerManagementIdleInhibitor(
            wayland_idle_notifier
        ).connect()
        print("Started")
        await asyncio.Event().wait()
    except asyncio.exceptions.CancelledError:
        print("Exiting")

if __name__ == "__main__":
    asyncio.run(main())
