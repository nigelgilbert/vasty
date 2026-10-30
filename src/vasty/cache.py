"""The local cache `~/.local/state/vasty/leases.json`.

The file holds `{"version": 1, "cached_at": EPOCH, "leases": {ID: LEASE}}` plus
the last instance listing and today's billed charges, which `status --cached`
reads. Files without those keys load with empty values.
Each lease serializes every `CachedLease` field by its type hints: Decimal as a
string, dataclasses as objects, int dict keys as strings. Load restores the
types, fills defaults for absent fields and ignores unknown keys. A value of
the wrong type marks the file corrupt.
"""

from __future__ import annotations

import dataclasses
import fcntl
import json
import os
import tempfile
import threading
import types
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import IO, Any, Literal, Union, get_args, get_origin, get_type_hints

from vasty.models import CachedLease, Charges, Instance

FORMAT_VERSION = 1


@dataclass
class CacheData:
    leases: dict[str, CachedLease] = field(default_factory=dict)
    cached_at: int | None = None
    rebuilt: bool = False
    instances: list[Instance] = field(default_factory=list)
    charges: Charges | None = None
    charges_at: int | None = None
    """When `charges` was fetched; billing data is fresh for 60s."""
    charges_start: int | None = None
    """The start of the UTC day `charges` covers."""


class CorruptCache(ValueError):
    """The cache file does not decode to `CacheData`."""


class Cache:
    """Read and write `leases.json` under an exclusive lock on `leases.json.lock`."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock_path = path.with_name(path.name + ".lock")
        self._mutex = threading.RLock()
        self._depth = 0
        self._lock_file: IO[bytes] | None = None

    def lock(self) -> AbstractContextManager[None]:
        """Hold the exclusive lock. Re-entrant within one process."""
        return self._locked()

    @contextmanager
    def _locked(self) -> Iterator[None]:
        with self._mutex:
            if self._depth == 0:
                self.lock_path.parent.mkdir(parents=True, exist_ok=True)
                handle = open(self.lock_path, "ab")
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                except BaseException:
                    handle.close()
                    raise
                self._lock_file = handle
            self._depth += 1
            try:
                yield
            finally:
                self._depth -= 1
                if self._depth == 0 and self._lock_file is not None:
                    fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_UN)
                    self._lock_file.close()
                    self._lock_file = None

    def load(self) -> CacheData:
        """Read the file. A corrupt file yields empty data with `rebuilt` set."""
        with self.lock():
            try:
                text = self.path.read_text(encoding="utf-8")
            except FileNotFoundError:
                return CacheData()
            except (OSError, UnicodeDecodeError):
                return CacheData(rebuilt=True)
            try:
                return decode(text)
            except CorruptCache:
                return CacheData(rebuilt=True)

    def save(self, data: CacheData) -> None:
        """Replace the file by temp file and rename."""
        text = encode(data)
        with self.lock():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(
                dir=self.path.parent, prefix=f".{self.path.name}.", suffix=".tmp"
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(text)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(tmp, self.path)
            except BaseException:
                try:
                    os.unlink(tmp)
                except FileNotFoundError:
                    pass
                raise


def encode(data: CacheData) -> str:
    """Render `CacheData` as the file's JSON text."""
    body = {
        "version": FORMAT_VERSION,
        "cached_at": data.cached_at,
        "leases": {key: _to_json(lease) for key, lease in data.leases.items()},
        "instances": _to_json(data.instances),
        "charges": _to_json(data.charges),
        "charges_at": data.charges_at,
        "charges_start": data.charges_start,
    }
    return json.dumps(body, indent=1, sort_keys=False) + "\n"


def decode(text: str) -> CacheData:
    """Parse the file's JSON text. Raise `CorruptCache` when it does not fit."""
    try:
        body = json.loads(text)
    except ValueError as exc:
        raise CorruptCache(str(exc)) from None
    if not isinstance(body, dict) or body.get("version") != FORMAT_VERSION:
        raise CorruptCache("unknown cache version")
    cached_at = _from_json(body.get("cached_at"), Union[int, None])
    raw_leases = body.get("leases")
    if not isinstance(raw_leases, dict):
        raise CorruptCache("leases is not an object")
    leases = {str(k): _from_json(v, CachedLease) for k, v in raw_leases.items()}
    return CacheData(
        leases=leases,
        cached_at=cached_at,
        instances=_from_json(body.get("instances", []), list[Instance]),
        charges=_from_json(body.get("charges"), Union[Charges, None]),
        charges_at=_from_json(body.get("charges_at"), Union[int, None]),
        charges_start=_from_json(body.get("charges_start"), Union[int, None]),
    )


def _to_json(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: _to_json(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _to_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_json(v) for v in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"cannot cache {type(value).__name__}")


def _from_json(value: Any, hint: Any) -> Any:
    origin = get_origin(hint)
    if origin is Union or origin is types.UnionType:
        args = get_args(hint)
        if value is None and type(None) in args:
            return None
        for arg in args:
            if arg is type(None):
                continue
            try:
                return _from_json(value, arg)
            except CorruptCache:
                continue
        raise CorruptCache(f"{value!r} fits no member of {hint}")
    if origin is Literal:
        if value in get_args(hint):
            return value
        raise CorruptCache(f"{value!r} is not one of {get_args(hint)}")
    if origin is list:
        if not isinstance(value, list):
            raise CorruptCache(f"{value!r} is not a list")
        (item,) = get_args(hint)
        return [_from_json(v, item) for v in value]
    if origin is dict:
        if not isinstance(value, dict):
            raise CorruptCache(f"{value!r} is not an object")
        key_hint, val_hint = get_args(hint)
        return {_key(k, key_hint): _from_json(v, val_hint) for k, v in value.items()}
    if hint is Any:
        return value
    if dataclasses.is_dataclass(hint) and isinstance(hint, type):
        return _dataclass(value, hint)
    if hint is Decimal:
        if not isinstance(value, str):
            raise CorruptCache(f"{value!r} is not a decimal string")
        try:
            return Decimal(value)
        except InvalidOperation:
            raise CorruptCache(f"{value!r} is not a decimal") from None
    if hint is bool:
        if isinstance(value, bool):
            return value
        raise CorruptCache(f"{value!r} is not a bool")
    if hint is int:
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        raise CorruptCache(f"{value!r} is not an int")
    if hint is float:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        raise CorruptCache(f"{value!r} is not a number")
    if hint is str:
        if isinstance(value, str):
            return value
        raise CorruptCache(f"{value!r} is not a string")
    raise CorruptCache(f"unsupported type {hint}")


def _key(key: str, hint: Any) -> Any:
    if hint is int:
        try:
            return int(key)
        except ValueError:
            raise CorruptCache(f"{key!r} is not an int key") from None
    return key


def _dataclass(value: Any, cls: type[Any]) -> Any:
    if not isinstance(value, dict):
        raise CorruptCache(f"{value!r} is not an object")
    hints = get_type_hints(cls)
    kwargs: dict[str, Any] = {}
    for f in dataclasses.fields(cls):
        if f.name in value:
            kwargs[f.name] = _from_json(value[f.name], hints[f.name])
        elif f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING:
            raise CorruptCache(f"{cls.__name__} lacks {f.name}")
    return cls(**kwargs)
