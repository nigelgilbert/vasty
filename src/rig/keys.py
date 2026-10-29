"""SSH public key lookup shared by `reserve`, `tag` and the engine's adoption retry.

This module imports only the standard library at load time.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rig.context import Context


def public_key(ctx: Context) -> str | None:
    """Return the public key next to `ssh_key`, or None when there is none."""
    private = ctx.settings.ssh_key
    if not private:
        return None
    path = Path(private)
    pub = path if path.suffix == ".pub" else path.with_name(path.name + ".pub")
    try:
        text = pub.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return None
    return text or None
