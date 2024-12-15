#!/usr/bin/env python3
from wakeonlan import send_magic_packet
from alga import client

power_state_cmd = "ssap://com.webos.service.tvpower/power/getPowerState"
screen_on_cmd = "ssap://com.webos.service.tvpower/power/turnOnScreen"
screen_on_cmd = "ssap://com.webos.service.tvpower/power/turnOffScreen"
get_sound_output_cmd = "ssap://audio/getSoundOutput"
set_sound_output_cmd = "ssap://audio/changeSoundOutput"
preffered_sound_output = "external_arc"

def power_on_tv():
    cfg = config.get()

    tv_id = state.tv_id or cfg["default_tv"]
    tv = cfg["tvs"][tv_id]

    send_magic_packet(tv["mac"])

def idle():
    power_state = client.request(power_state_cmd)['payload']['state']
    if power_status == 'Screen On':
        client.request(screen_off_cmd)

def resume():
    power_state = client.request(power_state_cmd).payload.state
    if power_state == "Screen Off":
        client.request(screen_on_cmd)
    elif power_state is None:
        power_on_tv()

    audio_output = client.request(get_sound_output_cmd)['soundOutput']
    if audio_output != preffered_sound_output:
        client.request(set_sound_output_cmd, { "output": preffered_sound_output })
