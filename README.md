# LGTV idle sync
`lgtv-idle-sync` ensures your lgtv turns off the screen when idling, turns on when resuming and turns on HDMI ARC device when a new audio stream is detected. It detects idling state in wayland, listens to xdg powermanagement inhibit events and pulseaudio audio streams (though I use that with pipewire). 
It tailors to my specific personal setup and is probably not useful somewhere else without code changes.

## Config
Configuration can be done through environment variables:
* `LGTV_SCREEN_IDLE_TIME`: The number of seconds before the screen should turn off
* `LGTV_SOUND_IDLE_TIME`: The number of seconds after which the HDMI ARC device turns off
