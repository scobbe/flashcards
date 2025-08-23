from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


# File-format constants
FRONT_BACK_DIVIDER: str = "---"
CARD_DIVIDER: str = "%%%"


@dataclass(frozen=True)
class CardField:
    name: str
    required: bool
    description: str
    ai_prompt: Optional[str] = None


@dataclass(frozen=True)
class CardSchema:
    name: str
    fields: List[CardField] = field(default_factory=list)


# Front side schema (content before FRONT_BACK_DIVIDER)
FRONT_SCHEMA = CardSchema(
    name="front",
    fields=[
        CardField(
            name="english",
            required=True,
            description="Short English definition/gloss for the headword.",
        ),
        CardField(
            name="subheader",
            required=False,
            description=(
                "Optional additional header on the front. Render as a third-level header (### ...). "
                "For decomposed cards, subword lines use the pattern: '### <subword> of "<english>"'."
            ),
        ),
    ],
)


# Back side schema (content after FRONT_BACK_DIVIDER, before CARD_DIVIDER)
BACK_SCHEMA = CardSchema(
    name="back",
    fields=[
        CardField(
            name="traditional",
            required=True,
            description="Traditional Chinese form(s) for the headword.",
        ),
        CardField(
            name="simplified",
            required=True,
            description="Simplified Chinese form(s) for the headword.",
        ),
    ],
)


__all__ = [
    "FRONT_BACK_DIVIDER",
    "CARD_DIVIDER",
    "CardField",
    "CardSchema",
    "FRONT_SCHEMA",
    "BACK_SCHEMA",
]


