#!/usr/bin/env python3
"""CLI commands for KDE custom shortcuts."""

import logging
import subprocess
from lgtv_idle_sync import lgtv_idle_client

logger = logging.getLogger(__name__)


def graceful_suspend():
    logging.basicConfig(level=logging.INFO)
    logger.info("Powering off TV")
    try:
        lgtv_idle_client.power_off()
    except Exception:
        logger.exception("Failed to power off TV, suspending anyway")
    logger.info("Suspending system")
    subprocess.run(["systemctl", "suspend"])


def screen_off():
    logging.basicConfig(level=logging.INFO)
    logger.info("Turning off screen")
    try:
        lgtv_idle_client.idle()
    except Exception:
        logger.exception("Failed to turn off screen")


def screen_on():
    logging.basicConfig(level=logging.INFO)
    logger.info("Turning on screen + soundbar")
    try:
        lgtv_idle_client.resume()
    except Exception:
        logger.exception("Failed to turn on screen")
