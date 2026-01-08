"""Card schema definitions."""

from lib.schema.base import (
    FRONT_BACK_DIVIDER,
    CARD_DIVIDER,
    PromptField,
    DisplayField,
)
from lib.schema.chinese import (
    CHINESE_PROMPT_PREAMBLE,
    CHINESE_PROMPT_FIELDS,
    CHINESE_DISPLAY_SCHEMA,
)
from lib.schema.english import (
    ENGLISH_PROMPT_PREAMBLE,
    ENGLISH_PROMPT_FIELDS,
    ENGLISH_DISPLAY_SCHEMA,
)

__all__ = [
    # Base
    "FRONT_BACK_DIVIDER",
    "CARD_DIVIDER",
    "PromptField",
    "DisplayField",
    # Chinese
    "CHINESE_PROMPT_PREAMBLE",
    "CHINESE_PROMPT_FIELDS",
    "CHINESE_DISPLAY_SCHEMA",
    # English
    "ENGLISH_PROMPT_PREAMBLE",
    "ENGLISH_PROMPT_FIELDS",
    "ENGLISH_DISPLAY_SCHEMA",
]
