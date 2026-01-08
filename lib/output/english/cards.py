"""English vocabulary card writing."""

from pathlib import Path
from typing import Dict, List, Optional

from lib.schema.base import FRONT_BACK_DIVIDER, CARD_DIVIDER
from lib.schema.english import (
    generate_system_prompt,
    format_field_for_display,
    extract_response_fields,
    get_required_field_names,
    ENGLISH_DISPLAY_SCHEMA,
)
from lib.common import OpenAIClient
from lib.common.cache import sanitize_filename, read_cache, write_cache

# Cache configuration
ENGLISH_CACHE_DIR = Path(__file__).parent.parent.parent.parent / "output" / "english" / "cache"
LOG_PREFIX = "english"


def generate_english_card_content(
    word: str,
    model: Optional[str] = None,
    verbose: bool = False,
) -> Dict[str, object]:
    """Generate definition, etymology, history, and pronunciation for an English word using OpenAI.

    Returns a dict with field names and values as defined in the English prompt schema.
    """
    # Check cache first (validate against schema-derived required fields)
    cached = read_cache(
        ENGLISH_CACHE_DIR, word,
        required_fields=get_required_field_names(),
        verbose=verbose,
        log_prefix=LOG_PREFIX,
    )
    if cached is not None:
        return cached

    client = OpenAIClient(model=model)

    # Generate system prompt from schema
    system = generate_system_prompt()
    user = f"Word: {word}"

    try:
        data = client.complete_json(system, user, verbose=verbose)

        # Extract and normalize fields using schema
        result = extract_response_fields(data)

        # Cache the result if we got valid data (at least one list field has content)
        if any(result.get(f) for f in ["definition", "etymology", "history"]):
            write_cache(ENGLISH_CACHE_DIR, word, result, verbose=verbose, log_prefix=LOG_PREFIX)

        return result
    except Exception:
        # Return empty result based on schema types
        return extract_response_fields({})


def write_english_card_md(
    out_dir: Path,
    file_base: str,
    word: str,
    content: Dict[str, object],
    verbose: bool = False,
) -> Path:
    """Write an English vocabulary flashcard.

    Args:
        out_dir: Output directory
        file_base: Filename base (e.g., "1.kakistocracy")
        word: Display word for card header (e.g., "kakistocracy")
        content: Card content dict with definition, etymology, history, pronunciation
        verbose: Enable verbose logging

    Card Format:
    ============
    FRONT:
    - H2: The word

    BACK:
    - --- separator
    - **definition:**
      - bullet 1
      - bullet 2
    - **etymology:**
      - bullet 1
      - bullet 2
    - **history:**
      - bullet 1
      - bullet 2
    - **pronunciation:** simple pronunciation
    - %%%
    """
    # Sanitize filename for invalid characters
    safe_file_base = sanitize_filename(file_base)
    md_path = out_dir / f"{safe_file_base}.md"
    parts: List[str] = []

    # Front: just the word (not file_base)
    parts.append(f"## {word}")
    parts.append(FRONT_BACK_DIVIDER)

    # Back: render fields in display schema order
    for display_field in ENGLISH_DISPLAY_SCHEMA:
        value = content.get(display_field.name)
        if not value:
            continue
        lines = format_field_for_display(display_field.name, value)
        parts.extend(lines)

    parts.append(CARD_DIVIDER)
    
    content_str = "\n".join(parts) + "\n"
    md_path.write_text(content_str, encoding="utf-8")
    
    if verbose:
        print(f"[english] [file] Created card: {md_path.name}")
    
    return md_path

