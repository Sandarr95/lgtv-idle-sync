import logging
from wakeonlan import send_magic_packet
from json.decoder import JSONDecodeError
from alga import client, state, config
from tenacity import retry, wait_exponential, stop_after_attempt

logger = logging.getLogger(__name__)

power_state_cmd = "ssap://com.webos.service.tvpower/power/getPowerState"
screen_on_cmd = "ssap://com.webos.service.tvpower/power/turnOnScreen"
screen_off_cmd = "ssap://com.webos.service.tvpower/power/turnOffScreen"
get_sound_output_cmd = "ssap://audio/getSoundOutput"
set_sound_output_cmd = "ssap://audio/changeSoundOutput"
preferred_sound_output = "external_arc"

def power_on_tv():
    logger.debug("Powering on the tv")
    cfg = config.get()

    tv_id = state.tv_id or cfg["default_tv"]
    tv = cfg["tvs"][tv_id]

    send_magic_packet(tv["mac"])

@retry(wait=wait_exponential(multiplier=0.5), stop=stop_after_attempt(3))
def idle():
    try:
        power_state = client.request(power_state_cmd)['state']
        if power_state == 'Active':
            logger.debug("Turning off the screen")
            client.request(screen_off_cmd)
    except JSONDecodeError:
        pass

@retry(wait=wait_exponential(multiplier=0.5), stop=stop_after_attempt(3))
def resume():
    try:
        power_state = client.request(power_state_cmd)['state']
        if power_state == "Screen Off":
            logger.debug("Turning on the screen")
            client.request(screen_on_cmd)

        _resume_audio()
    except JSONDecodeError:
        power_on_tv()

def _resume_audio():
    audio_output = client.request(get_sound_output_cmd)['soundOutput']
    if audio_output != preferred_sound_output:
        logger.debug("Activating the audio output")
        client.request(
            set_sound_output_cmd,
            { "output": preferred_sound_output }
        )

@retry(wait=wait_exponential(multiplier=0.5), stop=stop_after_attempt(3))
def resume_audio():
    try:
        _resume_audio()
    except JSONDecodeError:
        power_on_tv()
