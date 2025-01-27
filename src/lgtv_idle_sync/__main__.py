#!/usr/bin/env python3
import asyncio
import os
from lgtv_idle_sync.wayland_idle_notifier import WaylandIdleNotifier
from lgtv_idle_sync.powermanagement_idle_inhibitor import PowerManagementIdleInhibitor
from lgtv_idle_sync.pulseaudio_notifier import PulseAudioNotifier
from lgtv_idle_sync import lgtv_idle_client

async def main():
    try:
        lgtv_screen_idle_time = int(os.environ.get('LGTV_SCREEN_IDLE_TIME', "180"))
        lgtv_sound_idle_time = int(os.environ.get('LGTV_SOUND_IDLE_TIME', "120"))

        loop = asyncio.get_running_loop()
        wayland_idle_notifier = WaylandIdleNotifier(
            idle_timeout_secs=lgtv_screen_idle_time,
            idle_fn=lgtv_idle_client.idle,
            resume_fn=lgtv_idle_client.resume
        )

        def resume_audio():
            lgtv_idle_client.resume_audio()
            wayland_idle_notifier.reset_idling()

        pulseaudio_notifier = PulseAudioNotifier(
            resume_audio=resume_audio,
            min_secs_between_requests=lgtv_sound_idle_time
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
