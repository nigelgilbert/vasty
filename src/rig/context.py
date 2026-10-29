"""Per-invocation context: settings, provider, box access, cache, clock and I/O.

Every external effect goes through a field here so tests can swap it. The
provider and `vastai` load on first use.
"""

from __future__ import annotations

import os
import secrets
import shutil
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Mapping, TextIO

from rig.errors import RigError

if TYPE_CHECKING:
    from rig.cache import Cache
    from rig.config import Settings
    from rig.provider import Provider
    from rig.remote import BoxAccess
    from rig.timeutil import Clock


def default_http_get(url: str, headers: Mapping[str, str], timeout: float) -> int:
    """Return the HTTP status of a GET, or 0 when the connection fails."""
    request = urllib.request.Request(url, headers=dict(headers))
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status: int = response.status
            return status
    except urllib.error.HTTPError as exc:
        return exc.code
    except (urllib.error.URLError, OSError, TimeoutError):
        return 0


@dataclass
class Context:
    flags: dict[str, Any] = field(default_factory=dict)
    profile: str | None = None
    # Set the `[models]` entry that `settings` applies as the `model` layer before the first read.
    model: str | None = None
    stdin_json: dict[str, Any] | None = None
    mode: str = "json"
    env: Mapping[str, str] = field(default_factory=lambda: dict(os.environ))
    cwd: Path = field(default_factory=Path.cwd)
    home: Path = field(default_factory=Path.home)
    stdin: TextIO = field(default_factory=lambda: sys.stdin)
    stdout: TextIO = field(default_factory=lambda: sys.stdout)
    stderr: TextIO = field(default_factory=lambda: sys.stderr)
    stdin_tty: bool = False
    stdout_tty: bool = False
    wall: Callable[[], float] = time.time
    mono: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep
    random_hex: Callable[[int], str] = secrets.token_hex
    which: Callable[[str], str | None] = shutil.which
    http_get: Callable[[str, Mapping[str, str], float], int] = default_http_get
    provider_factory: Callable[[Context], Provider] | None = None
    box_factory: Callable[[Context], BoxAccess] | None = None
    _settings: Settings | None = None
    _provider: Provider | None = None
    _box: BoxAccess | None = None
    _clock: Clock | None = None
    _cache: Cache | None = None

    @property
    def state_dir(self) -> Path:
        return self.home / ".local" / "state" / "rig"

    @property
    def settings(self) -> Settings:
        if self._settings is None:
            from rig.config import resolve

            self._settings = resolve(
                self.flags, self.stdin_json, self.profile, self.env, self.cwd, self.home,
                stdin_text=self.stdin.read, model=self.model,
            )
        return self._settings

    @property
    def provider(self) -> Provider:
        if self._provider is None:
            if self.provider_factory is not None:
                self._provider = self.provider_factory(self)
            else:
                key_env = self.settings.api_key_env
                api_key = self.env.get(key_env)
                if not api_key:
                    raise RigError(
                        "auth_missing", f"No API key in {key_env}.", f"Export {key_env}."
                    )
                from rig.provider import VastProvider

                self._provider = VastProvider(api_key)
        return self._provider

    @property
    def box(self) -> BoxAccess:
        if self._box is None:
            if self.box_factory is not None:
                self._box = self.box_factory(self)
            else:
                from rig.remote import SshBox

                self._box = SshBox(self.settings.ssh_key, str(self.state_dir / "known_hosts"))
        return self._box

    @property
    def clock(self) -> Clock:
        if self._clock is None:
            from rig.timeutil import Clock

            self._clock = Clock(self._last_date, self.wall, self.mono)
        return self._clock

    def _last_date(self) -> tuple[float, float] | None:
        if self._provider is None:
            return None
        return self._provider.last_date()

    @property
    def cache(self) -> Cache:
        if self._cache is None:
            from rig.cache import Cache

            self._cache = Cache(self.state_dir / "leases.json")
        return self._cache

    def warn(self, line: str) -> None:
        """Write one diagnostic line to stderr."""
        print(line, file=self.stderr)
