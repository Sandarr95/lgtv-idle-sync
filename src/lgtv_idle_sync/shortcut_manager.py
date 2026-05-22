"""Install .desktop files for KDE custom shortcuts."""

import logging
import os
import shutil
import sys

logger = logging.getLogger(__name__)

DESKTOP_DIR = os.path.expanduser("~/.local/share/applications")

COMMANDS = [
    {
        "bin": "lgtv-graceful-suspend",
        "name": "LGTV Graceful Suspend",
        "comment": "Power off TV then suspend the system",
    },
    {
        "bin": "lgtv-screen-off",
        "name": "LGTV Screen Off",
        "comment": "Turn off the TV screen",
    },
    {
        "bin": "lgtv-screen-on",
        "name": "LGTV Screen On",
        "comment": "Turn on the TV screen and soundbar",
    },
]


def _resolve_command_path(name):
    bin_dir = os.path.dirname(sys.executable)
    candidate = os.path.join(bin_dir, name)
    if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
        return candidate
    return shutil.which(name)


def install_desktop_files():
    """Create .desktop files for all shortcut commands."""
    os.makedirs(DESKTOP_DIR, exist_ok=True)
    for cmd in COMMANDS:
        cmd_path = _resolve_command_path(cmd["bin"])
        if not cmd_path:
            logger.debug(f"{cmd['bin']} not in PATH, skipping")
            continue
        path = os.path.join(DESKTOP_DIR, f"{cmd['bin']}.desktop")
        with open(path, "w") as f:
            f.write(
                "[Desktop Entry]\n"
                f"Name={cmd['name']}\n"
                f"Comment={cmd['comment']}\n"
                f"Exec={cmd_path}\n"
                "Type=Application\n"
                "StartupNotify=false\n"
            )
        logger.info(f"Installed {path}")
