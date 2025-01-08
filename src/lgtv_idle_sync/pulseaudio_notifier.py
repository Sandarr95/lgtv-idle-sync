import asyncio
import time
from pulsectl_asyncio import PulseAsync
from pulsectl import PulseEventMaskEnum, PulseEventTypeEnum

class PulseAudioNotifier:
    def __init__(self, resume_audio, min_secs_between_requests=540): # My soundbars default timeout is 9 mins
        self._min_secs_between_requests = min_secs_between_requests
        self._last_resume_time = time.monotonic() - min_secs_between_requests
        self._resume_audio_fn = resume_audio

    def _time_between_requests_exceeded(self):
        now = time.monotonic()
        if now - self._last_resume_time > self._min_secs_between_requests:
            self._last_resume_time = now
            return True
        else:
            return False

    def _resume_audio(self):
        if self._time_between_requests_exceeded():
            self._resume_audio_fn()

    async def run(self):
        async with PulseAsync('event-printer') as pulse:
            async for event in pulse.subscribe_events(PulseEventMaskEnum.sink_input):
                if event.t == PulseEventTypeEnum.new:
                    self._resume_audio()
