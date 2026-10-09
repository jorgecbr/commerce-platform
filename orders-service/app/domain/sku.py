"""SKU value object.

A SKU is an identifier with a format, so it is modelled as a value object
instead of a bare ``str``. Once you hold a ``Sku`` you can trust it: you never
have to re-validate it before writing it to the database.
"""

import re
from dataclasses import dataclass

from app.domain.errors import InvalidSkuError

# Uppercase letters, digits and dashes; between 3 and 32 characters.
_SKU_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9-]{1,30}[A-Z0-9]$")


@dataclass(frozen=True, slots=True, order=True)
class Sku:
    """Stock keeping unit: the catalogue code of a product."""

    value: str

    def __post_init__(self) -> None:
        if not _SKU_PATTERN.match(self.value):
            raise InvalidSkuError(
                f"SKU must be 3-32 chars of A-Z, 0-9 or '-' and start/end alphanumeric: {self.value!r}"
            )

    def __str__(self) -> str:
        return self.value
