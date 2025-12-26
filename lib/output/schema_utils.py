"""Schema-related utilities for card generation."""

from typing import List, Tuple

from lib.schema.written import BACK_SCHEMA
from lib.schema.base import CardField


def _field_name_to_key(name: str) -> str:
    """Convert field name to JSON key format."""
    key = name.lower()
    # Remove parenthetical placeholders
    while True:
        start = key.find("(")
        end = key.find(")", start + 1)
        if start != -1 and end != -1:
            key = key[:start] + key[end + 1:]
        else:
            break
    key = key.replace(" ", "_").replace("-", "_")
    key = key.replace("__", "_").strip(" _")
    return key


def _build_back_json_shape() -> str:
    """Build the JSON shape for back fields from schema."""
    lines: List[str] = ["{"]
    
    def add_field(field: CardField, indent: int = 2):
        key = _field_name_to_key(field.name)
        if field.children:
            sublines: List[str] = []
            for ch in field.children or []:
                if ch.ai_prompt is None:
                    continue
                ck = _field_name_to_key(ch.name)
                sublines.append(" " * (indent + 2) + f'"{ck}": string,')
            if not sublines:
                return
            lines.append(" " * indent + f'"{key}": {{')
            if sublines[-1].strip().endswith(","):
                sublines[-1] = sublines[-1].rstrip(",")
            lines.extend(sublines)
            lines.append(" " * indent + "},")
        else:
            if field.ai_prompt is None:
                return
            if field.field_type == "sublist":
                lines.append(" " * indent + f'"{key}": [string, ...],')
            else:
                lines.append(" " * indent + f'"{key}": string,')

    for f in BACK_SCHEMA.fields:
        add_field(f)
    if lines[-1].strip().endswith(","):
        lines[-1] = lines[-1].rstrip(",")
    lines.append("}")
    return "\n".join(lines)


def _collect_guidelines() -> str:
    """Collect AI guidelines from schema."""
    bullets: List[str] = []
    
    def add_guidance(field: CardField, prefix: str = ""):
        key = _field_name_to_key(field.name)
        if field.ai_prompt:
            bullets.append(f"- {prefix}{key}: {field.ai_prompt}")
        for ch in field.children or []:
            add_guidance(ch, prefix=(prefix + key + ".") if prefix else (key + "."))
    
    for f in BACK_SCHEMA.fields:
        add_guidance(f)
    return "\n".join(bullets)


def _required_optional_keys() -> Tuple[List[str], List[str]]:
    """Get lists of required and optional keys from schema."""
    required: List[str] = []
    optional: List[str] = []
    
    def add_req_opt(field: CardField, prefix: str = ""):
        key = _field_name_to_key(field.name)
        if field.ai_prompt is not None:
            fq = f"{prefix}{key}" if prefix else key
            (required if field.required else optional).append(fq)
        for ch in field.children or []:
            next_prefix = f"{prefix}{key}." if (prefix or field.ai_prompt is not None) else ("" if not key else key + ".")
            add_req_opt(ch, prefix=next_prefix if next_prefix else "")
    
    for f in BACK_SCHEMA.fields:
        add_req_opt(f)
    return required, optional

