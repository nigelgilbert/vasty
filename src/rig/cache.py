"""The local cache `~/.local/state/rig/leases.json` (spec §8.1)."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from pathlib import Path

from rig.models import CachedLease


@dataclass
class CacheData:
    leases: dict[str, CachedLease] = field(default_factory=dict)
    cached_at: int | None = None
    rebuilt: bool = False


class Cache:
    """Read and write `leases.json` under an exclusive lock on `leases.json.lock`."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def lock(self) -> AbstractContextManager[None]:
        """Hold the exclusive lock. Re-entrant within one process."""
        raise NotImplementedError

    def load(self) -> CacheData:
        """Read the file. A corrupt file yields empty data with `rebuilt` set."""
        raise NotImplementedError

    def save(self, data: CacheData) -> None:
        """Replace the file by temp file and rename."""
        raise NotImplementedError
