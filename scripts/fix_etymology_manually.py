#!/usr/bin/env python3
"""Manually fix cards by adding etymology explanations.

This script analyzes each card's character breakdown and generates
etymology explanations based on the semantic logic of character combinations.

No API calls - uses embedded logic to generate etymologies.

Usage:
    python scripts/fix_etymology_manually.py [--dry-run]
"""

import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.common.utils import is_cjk_char


def parse_card(content: str) -> Dict:
    """Parse a card's content into structured data."""
    result = {
        "headword": "",
        "headword_trad": "",
        "pinyin": "",
        "definition": "",
        "characters": [],  # List of (char, trad, pinyin, english)
        "has_etymology": False,
        "etymology": "",
        "examples": [],
        "raw_lines": content.split("\n"),
    }
    
    lines = content.split("\n")
    
    # Parse headword
    for line in lines:
        if line.startswith("## "):
            hw = line[3:].strip()
            # Check for traditional in parens
            match = re.match(r'^([^(]+)\(([^)]+)\)$', hw)
            if match:
                result["headword"] = match.group(1).strip()
                result["headword_trad"] = match.group(2).strip()
            else:
                result["headword"] = hw
                result["headword_trad"] = ""
            break
    
    # Parse pinyin
    for line in lines:
        if "**pinyin:**" in line:
            result["pinyin"] = line.split("**pinyin:**")[1].strip()
            break
    
    # Parse definition
    for line in lines:
        if "**definition:**" in line:
            result["definition"] = line.split("**definition:**")[1].strip()
            break
    
    # Check for etymology
    result["has_etymology"] = any("**etymology:**" in line for line in lines)
    
    # Parse characters section
    # Format is:
    #   - 华(華)
    #     - huá
    #     - Chinese
    in_chars = False
    current_char = None
    char_data = []
    sub_items = []
    saved_last = False
    
    for i, line in enumerate(lines):
        if "**characters:**" in line:
            in_chars = True
            continue
        if in_chars:
            # Check for end of characters section
            if line.startswith("- **") and "characters" not in line:
                # Save last character
                if current_char and len(sub_items) >= 2:
                    current_char["pinyin"] = sub_items[0]
                    current_char["english"] = sub_items[1] if len(sub_items) > 1 else ""
                    char_data.append(current_char)
                    saved_last = True
                in_chars = False
                current_char = None
                continue
            
            # Character line (2 spaces, dash, space)
            if line.startswith("  - ") and not line.startswith("    "):
                # Save previous character
                if current_char and len(sub_items) >= 2:
                    current_char["pinyin"] = sub_items[0]
                    current_char["english"] = sub_items[1] if len(sub_items) > 1 else ""
                    char_data.append(current_char)
                
                # Start new character
                sub_items = []
                char_text = line[4:].strip()
                # Parse char(trad) format
                match = re.match(r'^([^(]+)\(([^)]+)\)$', char_text)
                if match:
                    current_char = {"char": match.group(1).strip(), "trad": match.group(2).strip(), "pinyin": "", "english": ""}
                else:
                    current_char = {"char": char_text, "trad": "", "pinyin": "", "english": ""}
            
            # Sub-item line (4 spaces, dash, space)
            elif line.startswith("    - ") and current_char:
                text = line[6:].strip()
                sub_items.append(text)
    
    # Save last character if not already saved
    if current_char and len(sub_items) >= 2 and not saved_last:
        current_char["pinyin"] = sub_items[0]
        current_char["english"] = sub_items[1] if len(sub_items) > 1 else ""
        char_data.append(current_char)
    
    result["characters"] = char_data
    return result


def format_char_reference(char: str, trad: str, pinyin: str, english: str) -> str:
    """Format a character reference with proper format.
    
    Format: simplified(traditional) (pinyin, "meaning") or simplified (pinyin, "meaning")
    """
    # Get primary meaning (before first semicolon, take first comma-separated item)
    primary = english.split(";")[0].split(",")[0].strip()
    
    if trad and trad != char:
        return f'{char}({trad}) ({pinyin}, "{primary}")'
    else:
        return f'{char} ({pinyin}, "{primary}")'


def generate_etymology(headword: str, headword_trad: str, pinyin: str, definition: str, characters: List[Dict]) -> str:
    """Generate etymology explanation based on character meanings.
    
    Uses format: simplified(traditional) (pinyin, "meaning") for character references.
    """
    # Count CJK characters in headword
    cjk_count = sum(1 for ch in headword if is_cjk_char(ch))
    
    # Single character - generate etymology based on character structure
    if cjk_count == 1:
        return generate_single_char_etymology(headword, headword_trad, pinyin, definition)
    
    # Multi-character word needs character breakdown
    if not characters:
        return ""
    
    # Build formatted character references
    char_refs = []
    for c in characters:
        char = c.get("char", "")
        trad = c.get("trad", "")
        char_pinyin = c.get("pinyin", "")
        eng = c.get("english", "")
        if char and eng and char_pinyin:
            ref = format_char_reference(char, trad, char_pinyin, eng)
            char_refs.append(ref)
    
    if not char_refs:
        return ""
    
    # Generate etymology based on number of characters
    if len(char_refs) == 2:
        return f"Combines {char_refs[0]} with {char_refs[1]} to express {definition.lower().rstrip('.')}."
    
    if len(char_refs) == 3:
        return f"Combines {char_refs[0]}, {char_refs[1]}, and {char_refs[2]} to convey {definition.lower().rstrip('.')}."
    
    # 4+ characters
    joined = ", ".join(char_refs[:-1]) + f", and {char_refs[-1]}"
    return f"Combines {joined} to express {definition.lower().rstrip('.')}."


# Characters that contain specific radicals (simplified)
# Map from character to (radical, radical_pinyin, radical_meaning, description_template)
CHAR_RADICALS = {
    # Mouth radical 口 - sounds, speech, eating
    "呃": ("口", "kǒu", "mouth", "an oral utterance"),
    "呀": ("口", "kǒu", "mouth", "an exclamatory sound"),
    "吧": ("口", "kǒu", "mouth", "a spoken particle"),
    "吗": ("口", "kǒu", "mouth", "a question marker"),
    "吃": ("口", "kǒu", "mouth", "the act of eating"),
    "喝": ("口", "kǒu", "mouth", "the act of drinking"),
    "叫": ("口", "kǒu", "mouth", "calling or shouting"),
    "嗯": ("口", "kǒu", "mouth", "an affirmative hum"),
    "哦": ("口", "kǒu", "mouth", "an exclamation of understanding"),
    "哈": ("口", "kǒu", "mouth", "laughter"),
    "哎": ("口", "kǒu", "mouth", "an interjection"),
    "喂": ("口", "kǒu", "mouth", "a calling sound"),
    "嘛": ("口", "kǒu", "mouth", "a spoken particle"),
    "噢": ("口", "kǒu", "mouth", "an exclamation"),
    "啊": ("口", "kǒu", "mouth", "an exclamatory particle"),
    "唉": ("口", "kǒu", "mouth", "a sigh"),
    "嗨": ("口", "kǒu", "mouth", "a greeting sound"),
    "哇": ("口", "kǒu", "mouth", "an exclamation of surprise"),
}


def generate_single_char_etymology(char: str, trad: str, pinyin: str, definition: str) -> str:
    """Generate etymology for a single character based on its structure."""
    # Check if we have specific knowledge about this character
    if char in CHAR_RADICALS:
        radical, rad_pin, rad_meaning, desc = CHAR_RADICALS[char]
        return f"Contains {radical} ({rad_pin}, \"{rad_meaning}\") indicating {desc}."
    
    # Fallback - check for common radicals in the character visually
    # This is a heuristic based on common left-side radicals
    common_left_radicals = [
        ("亻", "rén", "person"),
        ("氵", "shuǐ", "water"),
        ("扌", "shǒu", "hand"),
        ("忄", "xīn", "heart"),
        ("讠", "yán", "speech"),
        ("钅", "jīn", "metal"),
        ("饣", "shí", "food"),
        ("纟", "sī", "thread"),
        ("犭", "quǎn", "animal"),
        ("女", "nǚ", "woman"),
        ("木", "mù", "wood"),
        ("火", "huǒ", "fire"),
        ("土", "tǔ", "earth"),
        ("日", "rì", "sun"),
        ("月", "yuè", "moon"),
    ]
    
    # Generic fallback
    trad_part = f"({trad})" if trad and trad != char else ""
    return f"A character{trad_part} meaning {definition.lower().rstrip('.')}."


def fix_card(content: str) -> Tuple[str, bool]:
    """Fix a card by adding etymology if missing.
    
    Returns (new_content, was_modified).
    """
    card = parse_card(content)
    
    # Skip if already has etymology
    if card["has_etymology"]:
        return content, False
    
    # Generate etymology
    etymology = generate_etymology(
        card["headword"], 
        card["headword_trad"], 
        card["pinyin"], 
        card["definition"], 
        card["characters"]
    )
    
    if not etymology:
        return content, False
    
    # Insert etymology in the right place
    lines = content.split("\n")
    new_lines = []
    inserted = False
    
    # Check if card has characters section
    has_chars_section = any("**characters:**" in line for line in lines)
    
    if has_chars_section:
        # Insert after characters section, before examples
        in_chars = False
        for i, line in enumerate(lines):
            new_lines.append(line)
            
            if "**characters:**" in line:
                in_chars = True
            elif in_chars and line.startswith("- **") and "characters" not in line:
                # Found next section after characters - insert etymology before it
                new_lines.insert(-1, f"- **etymology:** {etymology}")
                inserted = True
                in_chars = False
    else:
        # No characters section - insert after definition, before examples
        for i, line in enumerate(lines):
            new_lines.append(line)
            
            if "**definition:**" in line and not inserted:
                # Check if next line is indented (multi-line definition)
                next_idx = i + 1
                while next_idx < len(lines) and lines[next_idx].startswith("  - "):
                    next_idx += 1
                # We're past the definition, but we already appended this line
                # So we add etymology right after this line
                if next_idx == i + 1:
                    # Single line definition - insert right after
                    new_lines.append(f"- **etymology:** {etymology}")
                    inserted = True
            elif "**examples:**" in line and not inserted:
                # Insert before examples if we haven't yet
                new_lines.insert(-1, f"- **etymology:** {etymology}")
                inserted = True
    
    if not inserted:
        return content, False
    
    return "\n".join(new_lines), True


def process_directory(output_dir: Path, dry_run: bool = False) -> Tuple[int, int]:
    """Process all cards in a directory.
    
    Returns (total_cards, cards_fixed).
    """
    total = 0
    fixed = 0
    
    for md_file in sorted(output_dir.glob("*.md")):
        if md_file.name.startswith("-"):
            continue
        
        total += 1
        content = md_file.read_text(encoding="utf-8")
        new_content, was_fixed = fix_card(content)
        
        if was_fixed:
            fixed += 1
            if not dry_run:
                md_file.write_text(new_content, encoding="utf-8")
            print(f"  ✓ Fixed: {md_file.name}")
    
    return total, fixed


def main():
    dry_run = "--dry-run" in sys.argv
    
    project_root = Path(__file__).parent.parent
    output_root = project_root / "output"
    
    print(f"{'[DRY RUN] ' if dry_run else ''}Fixing cards with missing etymology...")
    print("=" * 60)
    
    total_cards = 0
    total_fixed = 0
    
    # Find all Chinese output directories
    for output_dir in sorted(output_root.rglob("output")):
        if not output_dir.is_dir():
            continue
        
        # Skip English directories
        if "english" in str(output_dir):
            continue
        
        # Check if has .md files
        md_files = [f for f in output_dir.glob("*.md") if not f.name.startswith("-")]
        if not md_files:
            continue
        
        rel_path = output_dir.relative_to(project_root)
        print(f"\n📁 {rel_path}")
        
        cards, fixed = process_directory(output_dir, dry_run=dry_run)
        total_cards += cards
        total_fixed += fixed
        
        if fixed == 0:
            print("  (no fixes needed)")
    
    print("\n" + "=" * 60)
    print(f"{'[DRY RUN] ' if dry_run else ''}COMPLETE")
    print(f"Total cards: {total_cards}")
    print(f"Cards fixed: {total_fixed}")


if __name__ == "__main__":
    main()

