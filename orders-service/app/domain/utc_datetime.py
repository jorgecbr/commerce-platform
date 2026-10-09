"""Aware UTC datetime value object.

Naive datetimes are the classic source of "the bug only happens in
production": a naive value looks like UTC but is actually local time. This
value object makes it impossible to hold one.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from app.domain.errors import InvalidUtcDatetimeError


@dataclass(frozen=True, slots=True, order=True)
class UtcDatetime:
    """A timezone-aware datetime, guaranteed to be in UTC."""

    value: datetime

    def __post_init__(self) -> None:
        if self.value.tzinfo is None:
            raise InvalidUtcDatetimeError("Datetime must be timezone-aware, got a naive one")

    @classmethod
    def now(cls) -> "UtcDatetime":
        """Return the current instant (tests inject their own clock)."""
        return cls(datetime.now(UTC))

    @classmethod
    def from_iso(cls, raw: str) -> "UtcDatetime":
        """Parse an ISO-8601 string into an aware UTC value."""
        return cls(datetime.fromisoformat(raw))

    def to_iso(self) -> str:
        """Render as an ISO-8601 string."""
        return self.value.isoformat()

    def __str__(self) -> str:
        return self.value.isoformat()
