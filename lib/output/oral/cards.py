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
    
    system = """For each Chinese character, provide its pinyin and multiple English definitions.
Return JSON: {"characters": [{"char": "X", "trad": "X", "pinyin": "pīnyīn", "english": "def1; def2"}, ...]}

Rules:
1. One entry per character, in order
2. Pinyin must use tone marks (not numbers)
3. English definitions: UP TO 4 of the most common DISTINCT meanings
   - Use SEMICOLON (;) to separate distinct/different meanings
   - Use COMMA (,) only for synonyms or elaboration of the SAME meaning
   - Example: "I, me; my" — "I, me" are synonyms (same meaning), "my" is distinct
   - Example: "mountain, hill; peak" — "mountain, hill" are similar, "peak" is distinct
   - Avoid redundancy: don't list synonyms as separate meanings
   - Fewer definitions is better if additional would be redundant
   - NO trailing period
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
) -> List[Tuple[str, str, str]]:
    """Generate example sentences for a vocabulary word using OpenAI.
    
    Generates one example per meaning/definition.
    If input_examples is provided (from raw input), uses them as context.
    Returns a list of tuples: (chinese, pinyin, english)
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

FORMAT for each example - return a JSON object with three fields:
{"chinese": "...", "pinyin": "pīnyīn", "english": "English translation."}

CLAUSE-BY-CLAUSE TRADITIONAL FORMAT:
- Split the sentence by clause punctuation (，、；,;)
- For EVERY clause, show the traditional form in parentheses after the simplified
- Even if traditional is identical to simplified, still include the parenthetical
- Ending punctuation (。?！) goes at the very end

Examples:
- 我们坐着工作(我們坐著工作)，效率反而更高(效率反而更高)。
  (Both clauses have parentheticals, even though second is same)
- 你好吗(你好嗎)？
  (Single clause)
- 我吃饭(我吃飯)。
  (Single clause with traditional shown)
- 我说话(我說話)，他听(他聽)。
  (Both clauses with traditional)

Example for word 看到 with meanings "see (that); note":
{"examples": [
  {"chinese": "我看到他走了。", "pinyin": "wǒ kàn dào tā zǒu le", "english": "I saw him leave."},
  {"chinese": "请(請)看到这(這)个(個)问题(問題)的重要性。", "pinyin": "qǐng kàn dào zhège wèntí de zhòngyàoxìng", "english": "Please note the importance of this issue."}
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
        result: List[Tuple[str, str, str]] = []
        if isinstance(examples, list):
            for ex in examples:
                if isinstance(ex, dict):
                    # New format: {"chinese": "...", "pinyin": "...", "english": "..."}
                    ch = str(ex.get("chinese", "")).strip()
                    pin = str(ex.get("pinyin", "")).strip()
                    eng = str(ex.get("english", "")).strip()
                    if ch:
                        result.append((ch, pin, eng))
                elif isinstance(ex, str) and ex.strip():
                    # Legacy format: "chinese: pinyin; english"
                    if ": " in ex:
                        parts = ex.split(": ", 1)
                        ch = parts[0]
                        rest = parts[1] if len(parts) > 1 else ""
                        if "; " in rest:
                            pin, eng = rest.split("; ", 1)
                        else:
                            pin, eng = rest, ""
                        result.append((ch, pin, eng))
        return result
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
    examples: Optional[List[Tuple[str, str, str]]] = None,
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
    
    # Character breakdown for multi-character words (hierarchical format)
    if characters and len(characters) > 1:
        parts.append("- **characters:**")
        for ch_simp, ch_trad, ch_pin, ch_eng in characters:
            # Chinese characters as title
            if ch_trad and ch_trad != ch_simp:
                parts.append(f"  - {ch_simp}({ch_trad})")
            else:
                parts.append(f"  - {ch_simp}")
            # Pinyin indented
            parts.append(f"    - {ch_pin}")
            # English meanings indented
            parts.append(f"    - {ch_eng}")
    
    if examples:
        parts.append("- **examples:**")
        for ex in examples:
            # Examples are tuples: (chinese, pinyin, english)
            if isinstance(ex, tuple) and len(ex) >= 3:
                chinese_part, pinyin_part, english_part = ex[0], ex[1], ex[2]
                parts.append(f"  - {chinese_part}")
                if pinyin_part:
                    parts.append(f"    - {pinyin_part}")
                if english_part:
                    parts.append(f"    - {english_part}")
            elif isinstance(ex, str):
                # Legacy format fallback: "Chinese: pinyin; english"
                if ": " in ex:
                    ch, rest = ex.split(": ", 1)
                    if "; " in rest:
                        pin, eng = rest.split("; ", 1)
                    else:
                        pin, eng = rest, ""
                    parts.append(f"  - {ch}")
                    if pin:
                        parts.append(f"    - {pin}")
                    if eng:
                        parts.append(f"    - {eng}")
                else:
                    parts.append(f"  - {ex}")
    
    parts.append(CARD_DIVIDER)
    
    content = "\n".join(parts) + "\n"
    md_path.write_text(content, encoding="utf-8")
    if verbose:
        print(f"[oral] [file] Created card: {md_path.name}")
    return md_path
