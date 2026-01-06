#!/usr/bin/env python3
"""Fix front breadcrumbs format and component characters.

Front breadcrumbs: add "### from" header
### from
#### 1. definition1
#### 2. definition2

Component characters: look up pinyin/definition from other cards
"""

import re
import sys
from pathlib import Path


def extract_card_info(md_path: Path) -> tuple:
    """Extract english, traditional, simplified, pinyin from a markdown card file."""
    if not md_path.exists():
        return "", "", "", ""
    try:
        content = md_path.read_text(encoding="utf-8")
        english = ""
        traditional = ""
        simplified = ""
        pinyin = ""
        
        for line in content.split("\n"):
            if line.startswith("## "):
                english = line[3:].strip()
            elif line.startswith("- **traditional:**"):
                traditional = line.split(":**", 1)[1].strip() if ":**" in line else ""
            elif line.startswith("- **simplified:**"):
                simplified = line.split(":**", 1)[1].strip() if ":**" in line else ""
            elif line.startswith("- **pronunciation:**"):
                pinyin = line.split(":**", 1)[1].strip() if ":**" in line else ""
        
        return english, traditional, simplified, pinyin
    except Exception:
        pass
    return "", "", "", ""


def build_char_lookup(out_dir: Path) -> dict:
    """Build a lookup table of character info from all cards in directory."""
    lookup = {}
    for md_file in out_dir.glob("*.md"):
        if md_file.name.startswith("-"):
            continue
        eng, trad, simp, pin = extract_card_info(md_file)
        if simp and len(simp) == 1:
            lookup[simp] = (simp, trad or simp, pin, eng)
        if trad and len(trad) == 1 and trad != simp:
            lookup[trad] = (simp or trad, trad, pin, eng)
    return lookup


def migrate_file(file_path: Path, char_lookup: dict, dry_run: bool = False) -> bool:
    """Migrate a single markdown file."""
    content = file_path.read_text(encoding='utf-8')
    original = content
    
    lines = content.split('\n')
    result = []
    
    i = 0
    while i < len(lines):
        line = lines[i]
        
        # Add "### from" before H4 breadcrumbs if not already present
        if line.startswith("#### ") and re.match(r'^#### \d+\.', line):
            # Check if previous line is already "### from"
            if result and result[-1].strip() != "### from":
                result.append("### from")
        
        # Fix component characters missing info
        if "- **component characters:**" in line:
            result.append(line)
            i += 1
            # Process component character items
            while i < len(lines):
                item_line = lines[i]
                # Check if we've left the component characters section
                if item_line.strip().startswith("- **") and "component characters" not in item_line:
                    break
                if item_line.strip() == "%%%":
                    break
                if not item_line.strip():
                    result.append(item_line)
                    i += 1
                    continue
                    
                if not item_line.strip().startswith("- "):
                    result.append(item_line)
                    i += 1
                    continue
                
                item = item_line.strip()[2:]  # Remove "- "
                indent = len(item_line) - len(item_line.lstrip())
                pad = " " * indent
                
                # Check if already hierarchical (next line is more indented with "- ")
                if i + 1 < len(lines) and lines[i + 1].strip().startswith("- ") and len(lines[i + 1]) - len(lines[i + 1].lstrip()) > indent:
                    result.append(item_line)
                    i += 1
                    continue
                
                # Check if item already has parenthetical info
                if re.match(r'^.+\s+\([^)]+\)$', item):
                    # Parse existing format: Chinese (pinyin, "english")
                    match = re.match(r'^(.+?)\s+\(([^,]+),\s*"([^"]+)"\)$', item)
                    if match:
                        chinese_part = match.group(1)
                        pinyin_part = match.group(2).strip()
                        english_part = match.group(3).strip()
                        result.append(f"{pad}- {chinese_part}")
                        result.append(f"{pad}  - {pinyin_part}")
                        result.append(f"{pad}  - {english_part}")
                        i += 1
                        continue
                
                # Item is just a character - look up info
                char = item.strip()
                if len(char) <= 2 and char in char_lookup:
                    simp, trad, pin, eng = char_lookup[char]
                    if trad and trad != simp:
                        result.append(f"{pad}- {simp}({trad})")
                    else:
                        result.append(f"{pad}- {simp}")
                    if pin:
                        result.append(f"{pad}  - {pin}")
                    if eng:
                        result.append(f"{pad}  - {eng}")
                    i += 1
                    continue
                
                # No lookup found, keep as-is
                result.append(item_line)
                i += 1
            continue
        
        result.append(line)
        i += 1
    
    new_content = '\n'.join(result)
    
    if new_content != original:
        if not dry_run:
            file_path.write_text(new_content, encoding='utf-8')
        return True
    return False


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Fix front breadcrumbs and component characters')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--path', type=str, default='/Users/scobbe/src/flashcards/output')
    args = parser.parse_args()
    
    output_path = Path(args.path)
    if not output_path.exists():
        print(f"Error: {output_path} does not exist")
        sys.exit(1)
    
    # Process each output directory separately to build per-directory lookups
    modified_count = 0
    total_files = 0
    
    for out_dir in output_path.rglob('output'):
        if not out_dir.is_dir():
            continue
        
        md_files = [p for p in out_dir.glob('*.md') if not p.name.startswith('-')]
        if not md_files:
            continue
        
        # Build char lookup for this directory
        char_lookup = build_char_lookup(out_dir)
        
        for md_file in md_files:
            total_files += 1
            if migrate_file(md_file, char_lookup, dry_run=args.dry_run):
                modified_count += 1
                action = "Would modify" if args.dry_run else "Modified"
                print(f"{action}: {md_file}")
    
    print(f"\n{'Would modify' if args.dry_run else 'Modified'} {modified_count} files out of {total_files} total")
    
    if not args.dry_run and modified_count > 0:
        print("\nRegenerating combined -output.md files...")
        for out_dir in output_path.rglob('output'):
            if not out_dir.is_dir():
                continue
            
            md_files_in_dir = sorted([p for p in out_dir.glob('*.md') if not p.name.startswith('-')])
            if not md_files_in_dir:
                continue
            
            output_md = out_dir / '-output.md'
            parts = []
            for p in md_files_in_dir:
                try:
                    parts.append(p.read_text(encoding='utf-8', errors='ignore'))
                except Exception:
                    pass
            
            if parts:
                combined = '\n\n'.join(parts) + '\n'
                output_md.write_text(combined, encoding='utf-8')
        
        print("Done regenerating combined files")


if __name__ == '__main__':
    main()

