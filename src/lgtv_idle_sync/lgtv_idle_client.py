from wakeonlan import send_magic_packet
from json.decoder import JSONDecodeError
from alga import client, state, config

power_state_cmd = "ssap://com.webos.service.tvpower/power/getPowerState"
screen_on_cmd = "ssap://com.webos.service.tvpower/power/turnOnScreen"
screen_off_cmd = "ssap://com.webos.service.tvpower/power/turnOffScreen"
get_sound_output_cmd = "ssap://audio/getSoundOutput"
set_sound_output_cmd = "ssap://audio/changeSoundOutput"
preferred_sound_output = "external_arc"

def power_on_tv():
    cfg = config.get()

    tv_id = state.tv_id or cfg["default_tv"]
    tv = cfg["tvs"][tv_id]

    send_magic_packet(tv["mac"])

def idle():
    try:
        power_state = client.request(power_state_cmd)['state']
        if power_state == 'Active':
            client.request(screen_off_cmd)
    except JSONDecodeError:
        pass

def resume():
    try:
        power_state = client.request(power_state_cmd)['state']
        if power_state == "Screen Off":
            client.request(screen_on_cmd)

        audio_output = client.request(get_sound_output_cmd)['soundOutput']
        if audio_output != preferred_sound_output:
            client.request(
                set_sound_output_cmd,
                { "output": preferred_sound_output }
            )
    except JSONDecodeError:
        power_on_tv()

def resume_audio():
    try:
        audio_output = client.request(get_sound_output_cmd)['soundOutput']
        if audio_output != preferred_sound_output:
            client.request(
                set_sound_output_cmd,
                { "output": preferred_sound_output }
            )
    except JSONDecodeError:
        power_on_tv()
