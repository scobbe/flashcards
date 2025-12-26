"""Base schema types and constants shared by all card modes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


# File-format constants
FRONT_BACK_DIVIDER: str = "---"
CARD_DIVIDER: str = "%%%"


@dataclass(frozen=True)
class CardField:
    """Definition of a single field in a card schema."""
    name: str
    required: bool
    description: str
    ai_prompt: Optional[str] = None
    children: Optional[List["CardField"]] = None
    field_type: str = "line"  # "line" | "sublist" | "section"
    skip_if: Optional[Callable[[Dict[str, Any]], bool]] = None
    default_provider: Optional[Callable[[Dict[str, Any]], Any]] = None
    max_items: Optional[int] = None
    empty_fallback: Optional[str] = None


@dataclass(frozen=True)
class CardSchema:
    """Schema for one side of a flashcard."""
    name: str
    fields: List[CardField] = field(default_factory=list)


__all__ = [
    "FRONT_BACK_DIVIDER",
    "CARD_DIVIDER",
    "CardField",
    "CardSchema",
]

