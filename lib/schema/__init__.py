"""Card schema definitions."""

from lib.schema.base import (
    FRONT_BACK_DIVIDER,
    CARD_DIVIDER,
    CardField,
    CardSchema,
)
from lib.schema.written import (
    FRONT_SCHEMA,
    BACK_SCHEMA,
)
from lib.schema.oral import (
    ORAL_FRONT_SCHEMA,
    ORAL_BACK_SCHEMA,
)
from lib.schema.english import (
    ENGLISH_FRONT_SCHEMA,
    ENGLISH_BACK_SCHEMA,
)

__all__ = [
    # Base
    "FRONT_BACK_DIVIDER",
    "CARD_DIVIDER",
    "CardField",
    "CardSchema",
    # Written mode
    "FRONT_SCHEMA",
    "BACK_SCHEMA",
    # Oral mode
    "ORAL_FRONT_SCHEMA",
    "ORAL_BACK_SCHEMA",
    # English mode
    "ENGLISH_FRONT_SCHEMA",
    "ENGLISH_BACK_SCHEMA",
]

