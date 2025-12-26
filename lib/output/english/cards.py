"""English vocabulary card writing."""

import re
from pathlib import Path
from typing import Dict, List, Optional

from lib.schema.base import FRONT_BACK_DIVIDER, CARD_DIVIDER
from lib.common.openai import OpenAIClient


def _sanitize_filename(name: str) -> str:
    """Sanitize a string for use as a filename.
    
    Replaces invalid characters with underscores.
    """
    # Replace path separators and other problematic characters
    return re.sub(r'[/\\:*?"<>|]', '_', name)


def generate_english_card_content(
    word: str,
    model: Optional[str] = None,
) -> Dict[str, object]:
    """Generate definition, origin, and pronunciation for an English word using OpenAI.
    
    Returns a dict with keys: definition (list), origin (list), pronunciation (str)
    """
    client = OpenAIClient(model=model)
    
    system = """You are an expert lexicographer. Generate flashcard content for an English vocabulary word.

Return a JSON object with these keys:
{
  "definition": ["bullet point 1", "bullet point 2", ...],
  "origin": ["bullet point 1", "bullet point 2", ...],
  "pronunciation": "non-technical pronunciation"
}

RULES:

**definition** (1-3 bullet points):
- Provide clear, succinct definitions
- Use plain language, avoid jargon
- If the word has multiple distinct meanings, list each as a separate bullet
- Each bullet should be 1-2 lines max
- Start each bullet with a lowercase letter (no leading dash)

**origin** (2-3 bullet points):
- Explain where the word comes from (Greek, Latin, French, etc.)
- Include the original root word(s) and their meaning
- Add any interesting historical context or evolution of meaning
- Keep it engaging but concise
- Start each bullet with a lowercase letter (no leading dash)

**pronunciation** (single string):
- Use simple syllable breakdowns that anyone can read
- CAPITALIZE the stressed syllable
- Example: "kah-kis-TAH-kruh-see" for "kakistocracy"
- Do NOT use IPA symbols or phonetic notation
- Make it intuitive for a casual reader

Be accurate and informative, but keep everything succinct."""

    user = f"Word: {word}"
    
    try:
        data = client.complete_json(system, user)
        
        # Extract and validate fields
        definition = data.get("definition", [])
        if not isinstance(definition, list):
            definition = [str(definition)] if definition else []
        definition = [str(d).strip() for d in definition if d][:3]
        
        origin = data.get("origin", [])
        if not isinstance(origin, list):
            origin = [str(origin)] if origin else []
        origin = [str(o).strip() for o in origin if o][:3]
        
        pronunciation = str(data.get("pronunciation", "")).strip()
        
        return {
            "definition": definition,
            "origin": origin,
            "pronunciation": pronunciation,
        }
    except Exception:
        return {
            "definition": [],
            "origin": [],
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
        content: Card content dict with definition, origin, pronunciation
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
    - **origin:**
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
    
    # Back: definition, origin, pronunciation
    definition = content.get("definition", [])
    if isinstance(definition, list) and definition:
        parts.append("- **definition:**")
        for d in definition:
            parts.append(f"  - {d}")
    
    origin = content.get("origin", [])
    if isinstance(origin, list) and origin:
        parts.append("- **origin:**")
        for o in origin:
            parts.append(f"  - {o}")
    
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

