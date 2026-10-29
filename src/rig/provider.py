"""The adapter boundary between rig and Vast.ai (spec §10.2).

Every `vastai` import and call lives in this file. Code above it uses the
`Provider` protocol and the normalized rows in `rig.models`. `VastProvider`
imports `vastai` lazily inside its methods so stdlib-only commands stay fast.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol

from rig.errors import RigError
from rig.models import Charges, CreateRequest, Instance, Offer, OfferQuery, SshKey


class ProviderTimeout(RigError):
    """A create call timed out or lost its connection; the instance may exist."""

    def __init__(self, message: str) -> None:
        super().__init__("provider_error", message, "Run rig status.")


class Provider(Protocol):
    """The ten provider functions plus the latest response's `Date` header."""

    def search_offers(self, query: OfferQuery) -> list[Offer]: ...

    def create(self, request: CreateRequest) -> int:
        """Create an instance with SDK retries off and return its instance id.

        Raise `ProviderTimeout` on a timeout or connection error.
        """
        ...

    def list_instances(self) -> list[Instance]:
        """List every instance on the account, following `next_token`."""
        ...

    def get_instance(self, instance_id: int) -> Instance | None: ...

    def destroy(self, instance_id: int) -> None: ...

    def set_label(self, instance_id: int, label: str) -> None: ...

    def charges(self, start: int, end: int) -> Charges:
        """Return billed charges between two epoch seconds for every instance."""
        ...

    def balance(self) -> Decimal: ...

    def list_ssh_keys(self) -> list[SshKey]: ...

    def attach_ssh_key(self, public_key: str, instance_id: int | None = None) -> None:
        """Register the key on the account, or attach it to one instance when an id is given."""
        ...

    def last_date(self) -> tuple[float, float] | None:
        """Return the latest response's `Date` header as epoch seconds and the local monotonic time it arrived."""
        ...


class VastProvider:
    """`Provider` backed by the `vastai` SDK."""

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    def search_offers(self, query: OfferQuery) -> list[Offer]:
        raise NotImplementedError

    def create(self, request: CreateRequest) -> int:
        raise NotImplementedError

    def list_instances(self) -> list[Instance]:
        raise NotImplementedError

    def get_instance(self, instance_id: int) -> Instance | None:
        raise NotImplementedError

    def destroy(self, instance_id: int) -> None:
        raise NotImplementedError

    def set_label(self, instance_id: int, label: str) -> None:
        raise NotImplementedError

    def charges(self, start: int, end: int) -> Charges:
        raise NotImplementedError

    def balance(self) -> Decimal:
        raise NotImplementedError

    def list_ssh_keys(self) -> list[SshKey]:
        raise NotImplementedError

    def attach_ssh_key(self, public_key: str, instance_id: int | None = None) -> None:
        raise NotImplementedError

    def last_date(self) -> tuple[float, float] | None:
        raise NotImplementedError
