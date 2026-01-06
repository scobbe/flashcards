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


def generate_etymology(headword: str, definition: str, characters: List[Dict]) -> str:
    """Generate etymology explanation based on character meanings.
    
    Uses format: simplified(traditional) (pinyin, "meaning") for character references.
    """
    if not characters:
        return ""
    
    # Build formatted character references
    char_refs = []
    for c in characters:
        char = c.get("char", "")
        trad = c.get("trad", "")
        pinyin = c.get("pinyin", "")
        eng = c.get("english", "")
        if char and eng and pinyin:
            ref = format_char_reference(char, trad, pinyin, eng)
            char_refs.append(ref)
    
    if not char_refs:
        return ""
    
    # Generate etymology based on number of characters
    if len(char_refs) == 1:
        # Single character - we still want to note its components
        return ""  # Skip single chars without more context
    
    if len(char_refs) == 2:
        return f"Combines {char_refs[0]} with {char_refs[1]} to express {definition.lower().rstrip('.')}."
    
    if len(char_refs) == 3:
        return f"Combines {char_refs[0]}, {char_refs[1]}, and {char_refs[2]} to convey {definition.lower().rstrip('.')}."
    
    # 4+ characters
    joined = ", ".join(char_refs[:-1]) + f", and {char_refs[-1]}"
    return f"Combines {joined} to express {definition.lower().rstrip('.')}."


def fix_card(content: str) -> Tuple[str, bool]:
    """Fix a card by adding etymology if missing.
    
    Returns (new_content, was_modified).
    """
    card = parse_card(content)
    
    # Skip if already has etymology
    if card["has_etymology"]:
        return content, False
    
    # Generate etymology
    etymology = generate_etymology(card["headword"], card["definition"], card["characters"])
    
    if not etymology:
        return content, False
    
    # Insert etymology after characters section (or after definition if no characters)
    lines = content.split("\n")
    new_lines = []
    inserted = False
    
    # Find where to insert
    in_chars = False
    chars_ended = False
    
    for i, line in enumerate(lines):
        new_lines.append(line)
        
        if "**characters:**" in line:
            in_chars = True
        elif in_chars and line.startswith("- **") and "characters" not in line:
            # Found next section after characters - insert etymology before it
            new_lines.insert(-1, f"- **etymology:** {etymology}")
            inserted = True
            in_chars = False
        elif in_chars and line.startswith("- **examples:**"):
            # Examples section - insert etymology before it
            new_lines.insert(-1, f"- **etymology:** {etymology}")
            inserted = True
            in_chars = False
    
    # If not inserted yet (no characters section or at end), insert after definition
    if not inserted:
        new_lines2 = []
        for i, line in enumerate(new_lines):
            new_lines2.append(line)
            if "**definition:**" in line and not inserted:
                # Check if next line is indented (multi-line definition)
                if i + 1 < len(new_lines) and new_lines[i + 1].startswith("  - "):
                    continue  # Wait for definition to end
                new_lines2.append(f"- **etymology:** {etymology}")
                inserted = True
        new_lines = new_lines2
    
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

