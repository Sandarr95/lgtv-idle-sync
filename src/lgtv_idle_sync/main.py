#!/usr/bin/env python3
from lgtv_idle_sync import idle_monitor, lgtv_idle_client

if __name__ == "__main__":
    idle_monitor.start_monitoring(
        idle_function=lgtv_idle_client.idle,
        resume_function=lgtv_idle_client.resume
    )
