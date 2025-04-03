#!/usr/bin/env python3
import asyncio
import os
import sys
from lgtv_idle_sync.wayland_idle_manager import WaylandIdleManager
from lgtv_idle_sync.powermanagement_idle_inhibitor import PowerManagementIdleInhibitor
from lgtv_idle_sync.pulseaudio_notifier import PulseAudioNotifier
from lgtv_idle_sync import lgtv_idle_client

import logging
logger = logging.getLogger(__name__)

async def main():
    try:
        lgtv_screen_idle_time = int(os.environ.get('LGTV_SCREEN_IDLE_TIME', "180"))
        lgtv_sound_idle_time = int(os.environ.get('LGTV_SOUND_IDLE_TIME', "120"))

        loop = asyncio.get_running_loop()
        wayland_idle_manager = WaylandIdleManager(
            idle_timeout_secs=lgtv_screen_idle_time,
            idle_fn=lgtv_idle_client.idle,
            resume_fn=lgtv_idle_client.resume
        )

        def resume_audio():
            lgtv_idle_client.resume_audio()
            wayland_idle_manager.reset()

        pulseaudio_notifier = PulseAudioNotifier(
            resume_audio=resume_audio,
            min_secs_between_requests=lgtv_sound_idle_time
        )

        pwr_management_inhibitor = PowerManagementIdleInhibitor(
            wayland_idle_manager
        )

        tasks = [
            asyncio.create_task(wayland_idle_manager.run()),
            asyncio.create_task(pulseaudio_notifier.run()),
            asyncio.create_task(pwr_management_inhibitor.run())
        ]
        logger.info("Started")
        await asyncio.Event().wait()
    except asyncio.exceptions.CancelledError:
        logger.info("Exiting")

if __name__ == "__main__":
    log_level = logging.INFO if getattr(sys, 'frozen', False) else logging.DEBUG
    logging.basicConfig(level=log_level)
    asyncio.run(main())
