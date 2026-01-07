"""English vocabulary card writing."""

import json
import re
from pathlib import Path
from typing import Dict, List, Optional

from lib.schema.base import FRONT_BACK_DIVIDER, CARD_DIVIDER
from lib.common.openai import OpenAIClient, ENGLISH_CARD_SCHEMA

# Global cache directory for English card data
ENGLISH_CACHE_DIR = Path(__file__).parent.parent.parent.parent / "output" / "english" / "cache"


def _sanitize_filename(name: str) -> str:
    """Sanitize a string for use as a filename.

    Replaces invalid characters with underscores.
    """
    # Replace path separators and other problematic characters
    return re.sub(r'[/\\:*?"<>|]', '_', name)


def _get_cache_path(word: str) -> Path:
    """Get the cache file path for an English word."""
    safe_word = _sanitize_filename(word)
    return ENGLISH_CACHE_DIR / f"{safe_word}.json"


def _read_cache(word: str, verbose: bool = False) -> Optional[Dict]:
    """Read cached data for an English word. Returns None if not cached."""
    cache_path = _get_cache_path(word)
    if not cache_path.exists():
        return None
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        # Validate required fields
        if all(k in data for k in ["definition", "etymology", "history", "pronunciation"]):
            if verbose:
                print(f"[english] [cache] Loaded: {word}")
            return data
        return None
    except Exception:
        return None


def _write_cache(word: str, data: Dict, verbose: bool = False) -> None:
    """Write data to cache."""
    ENGLISH_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = _get_cache_path(word)
    cache_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if verbose:
        print(f"[english] [cache] Saved: {word}")


def generate_english_card_content(
    word: str,
    model: Optional[str] = None,
    verbose: bool = False,
) -> Dict[str, object]:
    """Generate definition, etymology, history, and pronunciation for an English word using OpenAI.

    Returns a dict with keys: definition (list), etymology (list), history (list), pronunciation (str)
    """
    # Check cache first
    cached = _read_cache(word, verbose=verbose)
    if cached is not None:
        return cached

    client = OpenAIClient(model=model)

    # Shorter prompt - schema enforces structure
    system = """Expert lexicographer. Generate flashcard content for an English word.
Definition: 1-3 clear bullets, plain language, lowercase start.
Etymology: 2-3 bullets on linguistic origins (language, roots, derivation).
History: 2-3 bullets on historical background (dates, context, evolution), NOT linguistics.
Pronunciation: simple syllables, CAPITALIZE stressed syllable (e.g. kah-kis-TAH-kruh-see)."""

    user = f"Word: {word}"

    try:
        data = client.complete_structured(system, user, ENGLISH_CARD_SCHEMA)

        # Extract and validate fields
        definition = data.get("definition", [])
        if not isinstance(definition, list):
            definition = [str(definition)] if definition else []
        definition = [str(d).strip() for d in definition if d][:3]

        etymology = data.get("etymology", [])
        if not isinstance(etymology, list):
            etymology = [str(etymology)] if etymology else []
        etymology = [str(e).strip() for e in etymology if e][:3]

        history = data.get("history", [])
        if not isinstance(history, list):
            history = [str(history)] if history else []
        history = [str(h).strip() for h in history if h][:3]

        pronunciation = str(data.get("pronunciation", "")).strip()

        result = {
            "definition": definition,
            "etymology": etymology,
            "history": history,
            "pronunciation": pronunciation,
        }

        # Cache the result if we got valid data
        if definition or etymology or history:
            _write_cache(word, result, verbose=verbose)

        return result
    except Exception:
        return {
            "definition": [],
            "etymology": [],
            "history": [],
            "pronunciation": "",
        }


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
    safe_file_base = _sanitize_filename(file_base)
    md_path = out_dir / f"{safe_file_base}.md"
    parts: List[str] = []
    
    # Front: just the word (not file_base)
    parts.append(f"## {word}")
    parts.append(FRONT_BACK_DIVIDER)
    
    # Back: definition, etymology, history, pronunciation
    definition = content.get("definition", [])
    if isinstance(definition, list) and definition:
        parts.append("- **definition:**")
        for d in definition:
            parts.append(f"  - {d}")

    etymology = content.get("etymology", [])
    if isinstance(etymology, list) and etymology:
        parts.append("- **etymology:**")
        for e in etymology:
            parts.append(f"  - {e}")

    history = content.get("history", [])
    if isinstance(history, list) and history:
        parts.append("- **history:**")
        for h in history:
            parts.append(f"  - {h}")

    pronunciation = content.get("pronunciation", "")
    if pronunciation:
        parts.append("- **pronunciation:**")
        parts.append(f"  - {pronunciation}")
    
    parts.append(CARD_DIVIDER)
    
    content_str = "\n".join(parts) + "\n"
    md_path.write_text(content_str, encoding="utf-8")
    
    if verbose:
        print(f"[english] [file] Created card: {md_path.name}")
    
    return md_path

