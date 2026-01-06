"""Card schema definitions."""

from lib.schema.base import (
    FRONT_BACK_DIVIDER,
    CARD_DIVIDER,
    CardField,
    CardSchema,
)
from lib.schema.chinese import (
    CHINESE_FRONT_SCHEMA,
    CHINESE_BACK_SCHEMA,
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
    # Chinese mode (unified)
    "CHINESE_FRONT_SCHEMA",
    "CHINESE_BACK_SCHEMA",
    # English mode
    "ENGLISH_FRONT_SCHEMA",
    "ENGLISH_BACK_SCHEMA",
]
