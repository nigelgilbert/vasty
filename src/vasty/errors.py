"""Stable error codes and the error object every command returns on failure.

Each code maps to one exit status. Raise `VastyError` anywhere below
the CLI; the CLI renders it and exits with its status.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

EXIT_CODES: dict[str, int] = {
    "invalid_arguments": 1,
    "invalid_config": 1,
    "auth_missing": 1,
    "dependency_missing": 1,
    "no_offers": 1,
    "lease_not_found": 1,
    "ambiguous_target": 1,
    "orphan_unmanaged": 1,
    "lease_expired": 1,
    "lease_pending": 1,
    "name_conflict": 1,
    "confirmation_required": 1,
    "model_unknown": 1,
    "image_unsupported": 1,
    "startup_too_large": 1,
    "vllm_missing": 1,
    "provider_error": 2,
    "box_unreachable": 2,
    "spend_unavailable": 2,
    "sync_failed": 2,
    "serve_failed": 2,
    "port_mapping_missing": 2,
    "budget_exceeded": 3,
}


@dataclass
class VastyError(Exception):
    """A failure with a stable code, a message and a runnable next action."""

    code: str
    message: str
    hint: str
    details: dict[str, Any] | None = field(default=None)

    def __post_init__(self) -> None:
        if self.code not in EXIT_CODES:
            raise ValueError(f"unknown error code {self.code!r}")
        super().__init__(self.message)

    @property
    def exit_code(self) -> int:
        return EXIT_CODES[self.code]

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"error": self.code, "message": self.message, "hint": self.hint}
        if self.details is not None:
            out["details"] = self.details
        return out


def invalid(message: str, hint: str = "Run vasty --help.") -> VastyError:
    """Build an `invalid_arguments` error."""
    return VastyError("invalid_arguments", message, hint)
