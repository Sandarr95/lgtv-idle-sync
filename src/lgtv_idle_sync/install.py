"""Install KDE custom shortcuts and the systemd user service."""

import logging
import os
import re
import shutil
import subprocess
import sys

logger = logging.getLogger(__name__)

DESKTOP_DIR = os.path.expanduser("~/.local/share/applications")
SYSTEMD_USER_DIR = os.path.expanduser("~/.config/systemd/user")
SERVICE_NAME = "lgtv-idle-sync.service"
DAEMON_BIN = "lgtv-idle-sync"

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

SERVICE_TEMPLATE = """[Unit]
Description=LG TV idle sync
After=graphical-session.target
PartOf=graphical-session.target

[Service]
Type=simple
ExecStart={exec_start}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=graphical-session.target
"""


_BREW_CELLAR_RE = re.compile(r"^(.*/\.linuxbrew)/Cellar/([^/]+)/[^/]+/")


def _resolve_command_path(name):
    # The binary in sys.executable's directory belongs to THIS install
    # (the venv that's running lgtv-install). Pick a path that survives
    # upgrades: brew's opt-symlink for Homebrew, the matching ~/.local/bin
    # entry for uv-tool, or fall back to the sibling itself.
    sibling = os.path.join(os.path.dirname(sys.executable), name)
    if not (os.path.isfile(sibling) and os.access(sibling, os.X_OK)):
        return shutil.which(name)

    # Homebrew: rewrite Cellar/<pkg>/<ver>/.../<name> → opt/<pkg>/bin/<name>
    m = _BREW_CELLAR_RE.match(os.path.realpath(sibling))
    if m:
        stable = f"{m.group(1)}/opt/{m.group(2)}/bin/{name}"
        if os.path.exists(stable):
            return stable

    # Otherwise (e.g. uv tool), prefer a PATH lookup if it points at THIS install.
    on_path = shutil.which(name)
    if on_path:
        try:
            if os.path.samefile(on_path, sibling):
                return on_path
        except OSError:
            pass
    return sibling


def install_desktop_files():
    """Create .desktop files for all shortcut commands."""
    os.makedirs(DESKTOP_DIR, exist_ok=True)
    for cmd in COMMANDS:
        cmd_path = _resolve_command_path(cmd["bin"])
        if not cmd_path:
            logger.warning(f"{cmd['bin']} not in PATH, skipping")
            continue
        path = os.path.join(DESKTOP_DIR, f"{cmd['bin']}.desktop")
        contents = (
            "[Desktop Entry]\n"
            f"Name={cmd['name']}\n"
            f"Comment={cmd['comment']}\n"
            f"Exec={cmd_path}\n"
            "Type=Application\n"
            "StartupNotify=false\n"
        )
        with open(path, "w") as f:
            f.write(contents)
        logger.info(f"Installed {path}")


def install_systemd_unit():
    """Write the systemd user service unit and reload the daemon."""
    daemon_path = _resolve_command_path(DAEMON_BIN)
    if not daemon_path:
        logger.error(f"{DAEMON_BIN} not in PATH, cannot install service")
        return
    os.makedirs(SYSTEMD_USER_DIR, exist_ok=True)
    service_path = os.path.join(SYSTEMD_USER_DIR, SERVICE_NAME)
    with open(service_path, "w") as f:
        f.write(SERVICE_TEMPLATE.format(exec_start=daemon_path))
    logger.info(f"Installed {service_path}")
    try:
        subprocess.run(
            ["systemctl", "--user", "daemon-reload"], check=True
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        logger.warning(
            "Failed to reload systemd; run `systemctl --user daemon-reload` manually"
        )


def install():
    """Entry point: install all shortcut files and the systemd unit."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    install_desktop_files()
    install_systemd_unit()
    print()
    print("Done. To enable autostart of the daemon:")
    print(f"  systemctl --user enable --now {SERVICE_NAME}")
    print()
    print("Custom shortcuts are available in System Settings →")
    print("Shortcuts → Add Application:")
    for cmd in COMMANDS:
        print(f"  - {cmd['name']}")
