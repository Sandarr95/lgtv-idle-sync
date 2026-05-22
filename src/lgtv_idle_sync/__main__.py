#!/usr/bin/env python3
import asyncio
import os
import sys
from lgtv_idle_sync.wayland_idle_manager import WaylandIdleManager
from lgtv_idle_sync.idle_policy import IdlePolicy
from lgtv_idle_sync.pulseaudio_notifier import PulseAudioNotifier
from lgtv_idle_sync.sleep_notifier import SleepNotifier
from lgtv_idle_sync import lgtv_idle_client

import logging
logger = logging.getLogger(__name__)

async def main():
    try:
        lgtv_screen_idle_time = int(os.environ.get('LGTV_SCREEN_IDLE_TIME', "180"))
        lgtv_sound_idle_time = int(os.environ.get('LGTV_SOUND_IDLE_TIME', "120"))

        wayland_idle_manager = WaylandIdleManager(
            idle_timeout_secs=lgtv_screen_idle_time,
        )

        idle_policy = IdlePolicy(
            wayland_idle_manager=wayland_idle_manager,
            idle_fn=lgtv_idle_client.idle,
            resume_fn=lgtv_idle_client.resume
        )

        wayland_idle_manager.set_callbacks(
            idle_fn=idle_policy.on_idled,
            resume_fn=idle_policy.on_resumed
        )

        pulseaudio_notifier = PulseAudioNotifier(
            resume_audio=lgtv_idle_client.resume_audio,
            min_secs_between_requests=lgtv_sound_idle_time
        )

        sleep_notifier = SleepNotifier(
            power_off_fn=lgtv_idle_client.power_off,
            power_on_fn=lgtv_idle_client.power_on,
            sleep_state_fn=idle_policy.set_sleeping
        )

        tasks = [
            asyncio.create_task(wayland_idle_manager.run()),
            asyncio.create_task(pulseaudio_notifier.run()),
            asyncio.create_task(idle_policy.run()),
            asyncio.create_task(sleep_notifier.run())
        ]
        logger.info("Started")
        await asyncio.Event().wait()
    except asyncio.exceptions.CancelledError:
        logger.info("Exiting")

def cli():
    log_level = logging.INFO
    logging.basicConfig(level=log_level)
    asyncio.run(main())

if __name__ == "__main__":
    log_level = logging.INFO if getattr(sys, 'frozen', False) else logging.DEBUG
    logging.basicConfig(level=log_level)
    asyncio.run(main())
