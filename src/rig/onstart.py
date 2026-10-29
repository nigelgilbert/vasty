"""The `onstart` script, startup wrapper and on-box watchdog (spec §5.1, §6)."""

from __future__ import annotations

ONSTART_LIMIT = 4048


def build_onstart(ttl: int, startup: str | None, custom_image: bool) -> str:
    """Build the encoded `onstart` command.

    Include the clock-file write, the env file, the startup wrapper and the
    user's script, compressed with gzip and base64. With a custom image, also
    include the watchdog and the essentials installer. Raise
    `startup_too_large` when the result exceeds 4048 characters.
    """
    raise NotImplementedError


def watchdog_script() -> str:
    """Return the watchdog shell script installed at `/workspace/.rig/watchdog.sh`."""
    raise NotImplementedError
