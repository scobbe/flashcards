"""Base schema types and utilities shared by all card modes."""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union


# =============================================================================
# File-format constants
# =============================================================================

FRONT_BACK_DIVIDER: str = "---"
CARD_DIVIDER: str = "%%%"


# =============================================================================
# Prompt Schema - Controls what we ask the AI for
# =============================================================================

@dataclass(frozen=True)
class PromptField:
    """A field in the AI prompt schema."""
    name: str
    prompt: Union[str, Dict[str, str]]  # str or {"single_char": ..., "multi_char": ...}
    response_type: str = "string"  # "string" | "list" | "boolean" | "dict"
    max_items: Optional[int] = None  # For list types, max number of items
    none_value: Optional[str] = None  # Value that means "not applicable"

    def get_prompt(self, variant: Optional[str] = None) -> str:
        """Get prompt text, optionally for a specific variant."""
        if isinstance(self.prompt, str):
            return self.prompt
        if variant:
            return self.prompt.get(variant, "")
        # Return first variant if no specific one requested
        return next(iter(self.prompt.values()), "")


def generate_system_prompt(
    preamble: Union[str, Dict[str, str]],
    fields: List[PromptField],
    variant: Optional[str] = None,
) -> str:
    """Generate system prompt from schema.

    Args:
        preamble: Intro text (str or dict with variants)
        fields: List of PromptField
        variant: Optional variant key (e.g., "single_char", "multi_char")
    """
    # Get preamble for variant
    if isinstance(preamble, dict):
        preamble_text = preamble.get(variant, "") if variant else next(iter(preamble.values()), "")
    else:
        preamble_text = preamble

    lines = [preamble_text, "Return JSON with these fields:"]

    for field in fields:
        prompt = field.get_prompt(variant)
        if prompt:
            lines.append(f"- {field.name}: {prompt}")

    return "\n".join(lines)


def extract_field_value(field: PromptField, raw_value: Any) -> Any:
    """Extract and normalize a field value from AI response based on schema.

    Args:
        field: The PromptField schema
        raw_value: Raw value from AI response

    Returns:
        Normalized value according to field's response_type
    """
    if raw_value is None:
        if field.response_type == "list":
            return []
        elif field.response_type == "boolean":
            return False
        elif field.response_type == "dict":
            return {}
        return ""

    if field.response_type == "list":
        if not isinstance(raw_value, list):
            raw_value = [raw_value] if raw_value else []
        # Preserve dicts, normalize strings
        result = []
        for item in raw_value:
            if item is None:
                continue
            if isinstance(item, dict):
                result.append(item)  # Preserve dict structure
            else:
                result.append(str(item).strip())
        # Apply max_items limit if specified
        if field.max_items:
            result = result[:field.max_items]
        return result

    elif field.response_type == "boolean":
        if isinstance(raw_value, bool):
            return raw_value
        if isinstance(raw_value, str):
            return raw_value.lower() in ("true", "yes", "1")
        return bool(raw_value)

    elif field.response_type == "dict":
        return raw_value if isinstance(raw_value, dict) else {}

    else:  # string
        return str(raw_value).strip() if raw_value else ""


def extract_response_fields(
    fields: List[PromptField],
    response_data: Dict[str, Any],
) -> Dict[str, Any]:
    """Extract and normalize all fields from AI response based on schema.

    Args:
        fields: List of PromptField schemas
        response_data: Raw AI response data

    Returns:
        Dict with normalized field values
    """
    result = {}
    for field in fields:
        raw_value = response_data.get(field.name)
        result[field.name] = extract_field_value(field, raw_value)
    return result


def get_required_field_names(fields: List[PromptField]) -> List[str]:
    """Get list of field names from schema for cache validation."""
    return [field.name for field in fields]


# =============================================================================
# Display Schema - Controls how we render the card markdown
# =============================================================================

@dataclass(frozen=True)
class DisplayField:
    """A field in the display schema."""
    name: str
    label: str  # Display label (e.g., "definition", "etymology")
    field_type: str = "line"  # "line" | "bullets" | "nested" | "nested_labeled"
    children: Optional[List[str]] = None  # For nested types, the sub-field names


def get_display_field(schema: List[DisplayField], name: str) -> Optional[DisplayField]:
    """Get a display field by name from a schema."""
    for f in schema:
        if f.name == name:
            return f
    return None


def get_display_order(schema: List[DisplayField]) -> List[str]:
    """Get the display field order from a schema."""
    return [f.name for f in schema]


def format_field_for_display(
    schema: List[DisplayField],
    field_name: str,
    value: Any,
    indent: int = 0,
) -> List[str]:
    """Format a field value for markdown display.

    Args:
        schema: The display schema to use
        field_name: Name of the field to format
        value: The value to format
        indent: Indentation level (for nested rendering)

    Returns:
        List of markdown lines
    """
    field = get_display_field(schema, field_name)
    if not field or not value:
        return []

    prefix = "  " * indent
    lines = []

    if field.field_type == "line":
        lines.append(f"{prefix}- **{field.label}:** {value}")

    elif field.field_type == "bullets":
        lines.append(f"{prefix}- **{field.label}:**")
        if isinstance(value, list):
            for item in value:
                lines.append(f"{prefix}  - {item}")
        else:
            lines.append(f"{prefix}  - {value}")

    elif field.field_type == "nested":
        # For components/examples: list of items with sub-fields
        lines.append(f"{prefix}- **{field.label}:**")
        if isinstance(value, list):
            for item in value:
                if isinstance(item, (list, tuple)):
                    # First element is the main value (with optional trad form)
                    main_val = item[0]
                    # Check for traditional form in second position
                    if len(item) > 1 and item[1] and item[1] != item[0]:
                        main_val = f"{item[0]}({item[1]})"
                    lines.append(f"{prefix}  - {main_val}")
                    # Remaining elements are sub-fields (skip trad which is index 1)
                    for i, child_name in enumerate(field.children or [], start=2):
                        if i < len(item) and item[i]:
                            lines.append(f"{prefix}    - {item[i]}")
                elif isinstance(item, dict):
                    # Dict with named fields - first key is main value
                    main_key = list(item.keys())[0] if item else None
                    if main_key:
                        lines.append(f"{prefix}  - {item[main_key]}")
                    for child_name in field.children or []:
                        if child_name in item and item[child_name]:
                            lines.append(f"{prefix}    - {item[child_name]}")

    elif field.field_type == "nested_labeled":
        # For etymology: dict with labeled sub-fields
        if isinstance(value, dict):
            has_content = any(value.get(c) for c in (field.children or []))
            if has_content:
                lines.append(f"{prefix}- **{field.label}:**")
                for child_name in field.children or []:
                    child_value = value.get(child_name)
                    if child_value:
                        # Special handling for description: split on " -> " and " = " into bullets, keeping delimiters
                        if child_name == "description" and (" -> " in child_value or " = " in child_value):
                            lines.append(f"{prefix}  - **{child_name}:**")
                            # Split on " -> ", keep delimiter at end of each part except last
                            arrow_parts = child_value.split(" -> ")
                            for i, arrow_part in enumerate(arrow_parts):
                                arrow_suffix = " ->" if i < len(arrow_parts) - 1 else ""
                                # Split on " = ", keep delimiter at end of each part except last
                                eq_parts = arrow_part.split(" = ")
                                for j, eq_part in enumerate(eq_parts):
                                    eq_suffix = " =" if j < len(eq_parts) - 1 else arrow_suffix
                                    lines.append(f"{prefix}    - {eq_part.strip()}{eq_suffix}")
                        else:
                            lines.append(f"{prefix}  - **{child_name}:** {child_value}")

    return lines


__all__ = [
    # Constants
    "FRONT_BACK_DIVIDER",
    "CARD_DIVIDER",
    # Prompt schema
    "PromptField",
    "generate_system_prompt",
    "extract_field_value",
    "extract_response_fields",
    "get_required_field_names",
    # Display schema
    "DisplayField",
    "get_display_field",
    "get_display_order",
    "format_field_for_display",
]
