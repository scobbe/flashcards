"""English flashcard schemas - source of truth for AI prompts and display formatting."""

from typing import List

from lib.schema.base import (
    PromptField,
    DisplayField,
    generate_system_prompt as _generate_system_prompt,
    format_field_for_display as _format_field_for_display,
    get_display_field as _get_display_field,
    get_display_order as _get_display_order,
    extract_response_fields as _extract_response_fields,
    get_required_field_names as _get_required_field_names,
)


# =============================================================================
# Prompt Schema - Controls what we ask the AI for
# =============================================================================

ENGLISH_PROMPT_PREAMBLE = "English vocabulary expert."

ENGLISH_PROMPT_FIELDS = [
    PromptField(
        name="definition",
        prompt=(
            "array of 1-3 clear, succinct definitions. Include relevant dates when applicable "
            "(birth/death for people, years for events). Format: [\"def1\", \"def2\", ...]"
        ),
        response_type="list",
        max_items=3,
    ),
    PromptField(
        name="etymology",
        prompt=(
            "array of 2-3 bullets on linguistic origins: language of origin (Greek, Latin, etc.), "
            "root words and their literal meaning, how the word was derived. "
            "Format: [\"bullet1\", \"bullet2\", ...]"
        ),
        response_type="list",
        max_items=3,
    ),
    PromptField(
        name="history",
        prompt=(
            "array of 2-3 bullets on historical background: when it first appeared, "
            "historical context, how usage evolved, notable associations. "
            "Format: [\"bullet1\", \"bullet2\", ...]"
        ),
        response_type="list",
        max_items=3,
    ),
    PromptField(
        name="pronunciation",
        prompt=(
            "Simple syllable breakdown with STRESSED syllable capitalized. "
            "Example: \"kah-kis-TAH-kruh-see\" for kakistocracy. Do NOT use IPA."
        ),
        response_type="string",
    ),
]


def generate_system_prompt() -> str:
    """Generate the system prompt for English card generation."""
    return _generate_system_prompt(ENGLISH_PROMPT_PREAMBLE, ENGLISH_PROMPT_FIELDS)


def extract_response_fields(response_data: dict) -> dict:
    """Extract and normalize AI response fields based on schema."""
    return _extract_response_fields(ENGLISH_PROMPT_FIELDS, response_data)


def get_required_field_names() -> List[str]:
    """Get list of required field names for cache validation."""
    return _get_required_field_names(ENGLISH_PROMPT_FIELDS)


# =============================================================================
# Display Schema - Controls how we render the card markdown
# =============================================================================

ENGLISH_DISPLAY_SCHEMA = [
    DisplayField(name="definition", label="definition", field_type="bullets"),
    DisplayField(name="etymology", label="etymology", field_type="bullets"),
    DisplayField(name="history", label="history", field_type="bullets"),
    DisplayField(name="pronunciation", label="pronunciation", field_type="bullets"),
]


def format_field_for_display(field_name: str, value) -> List[str]:
    """Format a field value for markdown display."""
    return _format_field_for_display(ENGLISH_DISPLAY_SCHEMA, field_name, value)


def get_display_field(name: str):
    """Get a display field by name."""
    return _get_display_field(ENGLISH_DISPLAY_SCHEMA, name)


def get_display_order() -> List[str]:
    """Get the display field order."""
    return _get_display_order(ENGLISH_DISPLAY_SCHEMA)


__all__ = [
    # Prompt schema
    "ENGLISH_PROMPT_PREAMBLE",
    "ENGLISH_PROMPT_FIELDS",
    "generate_system_prompt",
    "extract_response_fields",
    "get_required_field_names",
    # Display schema
    "ENGLISH_DISPLAY_SCHEMA",
    "format_field_for_display",
    "get_display_field",
    "get_display_order",
]
