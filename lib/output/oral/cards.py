"""Oral mode card writing."""

import json
from pathlib import Path
from typing import List, Optional, Tuple

from lib.schema.base import FRONT_BACK_DIVIDER, CARD_DIVIDER
from lib.common.openai import OpenAIClient
from lib.common.utils import is_cjk_char


def generate_character_breakdown(
    simplified: str,
    traditional: str,
    model: Optional[str] = None,
) -> List[Tuple[str, str, str, str]]:
    """Get pinyin and definition for each character in a multi-character word.
    
    Returns list of (simplified_char, traditional_char, pinyin, english) tuples.
    Only called for words with more than one character.
    """
    # Filter to only CJK characters
    chars = [ch for ch in simplified if is_cjk_char(ch)]
    if len(chars) <= 1:
        return []
    
    client = OpenAIClient(model=model)
    
    system = """For each Chinese character, provide its pinyin and a brief English definition.
Return JSON: {"characters": [{"char": "X", "trad": "X", "pinyin": "pīnyīn", "english": "definition"}, ...]}

Rules:
1. One entry per character, in order
2. Pinyin must use tone marks (not numbers)
3. English definition should be 1-4 words, the most common meaning
4. If traditional differs from simplified, include it in "trad", otherwise repeat the simplified
5. Do NOT censor or filter profanity/vulgarity - include exact definitions
"""
    
    user = f"Characters: {' '.join(chars)}"
    if traditional and traditional != simplified:
        user += f"\n(Traditional form of word: {traditional})"
    
    try:
        data = client.complete_json(system, user)
        chars_data = data.get("characters", [])
        result: List[Tuple[str, str, str, str]] = []
        for item in chars_data:
            if isinstance(item, dict):
                ch = str(item.get("char", "")).strip()
                trad = str(item.get("trad", ch)).strip()
                pin = str(item.get("pinyin", "")).strip()
                eng = str(item.get("english", "")).strip()
                if ch:
                    result.append((ch, trad, pin, eng))
        return result
    except Exception:
        return []


def generate_example_sentences(
    simplified: str,
    traditional: str,
    pinyin: str,
    english: str,
    input_examples: Optional[str] = None,
    model: Optional[str] = None,
) -> List[str]:
    """Generate example sentences for a vocabulary word using OpenAI.
    
    Generates one example per meaning/definition.
    If input_examples is provided (from raw input), uses them as context.
    Returns a list of sentences in format: simplified(traditional) (pinyin, "English")
    """
    client = OpenAIClient(model=model)
    
    word = simplified or traditional
    trad_word = traditional if traditional and traditional != simplified else ""
    
    system = """Generate and format example sentences for a Chinese vocabulary word.
Output a JSON object with key "examples" containing an array of formatted example sentences.

STRUCTURE (in this exact order):
1. FIRST: Generate ONE ideal example sentence PER PRONUNCIATION/MEANING
   - If definition contains "|" (pipe), these are DIFFERENT PRONUNCIATIONS - generate one example for EACH
   - If definition contains ";" (single semicolon), these are related meanings under ONE pronunciation
   - Each example MUST demonstrate that SPECIFIC meaning with the correct pronunciation!
   - Example: pinyin "jǐ, jī" with definition "how many; several | almost; small table" → need 2 examples: one for jǐ (how many), one for jī (almost)
   - Put these FIRST in the array, in the same order as the pronunciations/definitions
2. THEN: If input examples are provided, format ALL OF THEM and add after the ideal examples
   - Do NOT skip any input examples

FORMAT for each example:
simplified句子(traditional句子) (pīnyīn, "English translation")

- If the sentence has traditional characters that differ from simplified, show the ENTIRE traditional sentence in parentheses
- Example: 我说话(我說話) (wǒ shuōhuà, "I speak")
- If no traditional differs, just show: 我吃饭 (wǒ chīfàn, "I eat")

Example for word 看到 with meanings "see (that); note":
{"examples": [
  "我看到他走了 (wǒ kàn dào tā zǒu le, \\"I saw him leave\\")",
  "请看到这个问题的重要性(請看到這個問題的重要性) (qǐng kàn dào zhège wèntí de zhòngyàoxìng, \\"Please note the importance of this issue\\")"
]}

The first example demonstrates "see", the second demonstrates "note" - each meaning gets its own example.

IMPORTANT: Do NOT censor or filter profanity/vulgarity - include exact translations."""

    user = f"Word: {word}"
    if trad_word:
        user += f" (traditional: {trad_word})"
    user += f"\nPinyin: {pinyin}\nMeaning(s): {english}"
    
    # Include input examples - ALL must be formatted after ideal examples
    if input_examples and input_examples.strip():
        user += f"\n\nINPUT EXAMPLES (format ALL of these AFTER the ideal example(s)):\n{input_examples}"
    else:
        user += "\n\nNo input examples provided - just generate 1-2 ideal examples."
    
    try:
        data = client.complete_json(system, user)
        examples = data.get("examples", [])
        if isinstance(examples, list):
            return [ex for ex in examples if isinstance(ex, str) and ex.strip()]
        return []
    except Exception:
        return []


def write_oral_card_md(
    out_dir: Path,
    word: str,
    simplified: str,
    traditional: str,
    pinyin: str,
    english: str,
    relation: str,
    parent_chinese: str = "",
    examples: Optional[List[str]] = None,
    characters: Optional[List[Tuple[str, str, str, str]]] = None,
    verbose: bool = False,
) -> Path:
    """Write an oral practice card with Chinese on front, pinyin+English on back.
    
    Card Format:
    ============
    FRONT (Chinese only, except structural labels):
    - H2: Simplified(Traditional) if different, or just Simplified
    - H3: "sub-word" (if applicable)
    - H4: Parent Chinese(Traditional) - NO pinyin on front
    
    BACK:
    - --- separator
    - **pinyin:** this word's pinyin
    - **definition:** English
    - **examples:**
      - example1
      - example2
    - %%%
    """
    md_path = out_dir / f"{word}.md"
    parts: List[str] = []
    
    # Build the Chinese heading with traditional in parentheses if different
    if traditional and traditional != simplified:
        chinese_heading = f"{simplified}({traditional})"
    else:
        chinese_heading = simplified
    
    parts.append(f"## {chinese_heading}")
    
    # Handle sub-word relation - only Chinese on front, NO PINYIN
    rel = relation.strip()
    if rel:
        rel_norm = rel.replace("subword", "sub-word").replace("subcomponent", "sub-component")
        if rel_norm.startswith("sub-word of ") or rel_norm.startswith("sub-component of "):
            rel_type = "sub-word" if rel_norm.startswith("sub-word of ") else "sub-component"
            parts.append(f"### {rel_type}")
            # Show parent word in Chinese only - NO PINYIN on front
            if parent_chinese:
                parts.append(f"#### {parent_chinese}")
        else:
            parts.append(f"### {rel_norm}")
    
    parts.append(FRONT_BACK_DIVIDER)
    parts.append(f"- **pinyin:** {pinyin}")
    
    # Check if there are multiple pronunciations with different definitions
    # Format: pinyin = "jǐ, jī" and english = "how many | almost"
    pinyins = [p.strip() for p in pinyin.split(",")]
    definitions = [d.strip() for d in english.split("|")]
    
    if len(pinyins) > 1 and len(definitions) == len(pinyins):
        # Multi-pronunciation format: each definition on its own line with pinyin prefix
        parts.append("- **definition:**")
        for pin, defn in zip(pinyins, definitions):
            parts.append(f"  - {pin}: {defn}")
    else:
        # Single pronunciation or mismatched counts: use simple format
        parts.append(f"- **definition:** {english}")
    
    # Character breakdown for multi-character words
    if characters and len(characters) > 1:
        parts.append("- **characters:**")
        for ch_simp, ch_trad, ch_pin, ch_eng in characters:
            if ch_trad and ch_trad != ch_simp:
                parts.append(f"  - {ch_simp}({ch_trad}): {ch_pin}, {ch_eng}")
            else:
                parts.append(f"  - {ch_simp}: {ch_pin}, {ch_eng}")
    
    if examples:
        parts.append("- **examples:**")
        for ex in examples:
            parts.append(f"  - {ex}")
    
    parts.append(CARD_DIVIDER)
    
    content = "\n".join(parts) + "\n"
    md_path.write_text(content, encoding="utf-8")
    if verbose:
        print(f"[oral] [file] Created card: {md_path.name}")
    return md_path
