#!/usr/bin/env python3
"""Fix breadcrumbs format and component characters.

Front breadcrumbs: separate H4 lines
#### 1. definition1
#### 2. definition2

Back breadcrumbs: hierarchical array
- **breadcrumbs:**
  - 学校(學校)
    - xué xiào
    - school
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


def find_parent_by_english(out_dir: Path, parent_english: str) -> tuple:
    """Find parent file by English heading and return its info."""
    for candidate in out_dir.glob("*.md"):
        if candidate.name.startswith("-"):
            continue
        eng, trad, simp, pin = extract_card_info(candidate)
        if eng == parent_english:
            return eng, trad, simp, pin
    return "", "", "", ""


def migrate_file(file_path: Path, dry_run: bool = False) -> bool:
    """Migrate a single markdown file."""
    content = file_path.read_text(encoding='utf-8')
    original = content
    out_dir = file_path.parent
    
    lines = content.split('\n')
    result = []
    
    i = 0
    while i < len(lines):
        line = lines[i]
        
        # Fix H3 breadcrumbs to H4 lines
        # e.g., "### 1. def1 / 2. def2" -> "#### 1. def1" + "#### 2. def2"
        # or "### 1. school" -> "#### 1. school"
        if line.startswith("### ") and re.match(r'^### \d+\.', line):
            content_part = line[4:]
            # Check if combined with " / "
            if " / " in content_part:
                parts_list = re.split(r'\s*/\s*', content_part)
                for part in parts_list:
                    part = part.strip()
                    if part:
                        result.append(f"#### {part}")
            else:
                result.append(f"#### {content_part}")
            i += 1
            continue
        
        # Fix inline breadcrumbs to hierarchical format
        # From: - **breadcrumbs:** 学校(學校)(xué xiào)
        # To:   - **breadcrumbs:**
        #         - 学校(學校)
        #           - xué xiào
        #           - school
        if line.startswith("- **breadcrumbs:**") and not line.strip() == "- **breadcrumbs:**":
            content_part = line.split(":**", 1)[1].strip() if ":**" in line else ""
            if content_part:
                result.append("- **breadcrumbs:**")
                # Parse breadcrumb entries separated by " > "
                entries = content_part.split(" > ")
                for entry in entries:
                    entry = entry.strip()
                    # Parse format: 学校(學校)(xué xiào) or 学校(xué xiào)
                    # or simpler: 得(得)(de; dé)
                    match = re.match(r'^(.+?)\((.+?)\)\((.+?)\)$', entry)
                    if match:
                        simp = match.group(1)
                        trad = match.group(2)
                        pin = match.group(3)
                        
                        # Try to find the English definition by looking up the file
                        eng_def = ""
                        for candidate in out_dir.glob("*.md"):
                            if candidate.name.startswith("-"):
                                continue
                            c_eng, c_trad, c_simp, _ = extract_card_info(candidate)
                            if c_simp == simp or c_trad == trad:
                                eng_def = c_eng
                                break
                        
                        if trad != simp:
                            result.append(f"  - {simp}({trad})")
                        else:
                            result.append(f"  - {simp}")
                        result.append(f"    - {pin}")
                        if eng_def:
                            result.append(f"    - {eng_def}")
                    else:
                        # Try simpler format
                        match2 = re.match(r'^(.+?)\((.+?)\)$', entry)
                        if match2:
                            simp = match2.group(1)
                            rest = match2.group(2)
                            result.append(f"  - {simp}({rest})")
                        else:
                            result.append(f"  - {entry}")
                i += 1
                continue
        
        # Fix component characters without pinyin/definition
        # Just convert inline format to hierarchical where possible
        if "- **component characters:**" in line:
            result.append(line)
            i += 1
            # Process component character items
            while i < len(lines):
                item_line = lines[i]
                if not item_line.strip().startswith("- ") or item_line.strip().startswith("- **"):
                    break
                
                item = item_line.strip()[2:]  # Remove "- "
                indent = len(item_line) - len(item_line.lstrip())
                pad = " " * indent
                
                # Check if already hierarchical
                if i + 1 < len(lines) and lines[i + 1].startswith(pad + "  - "):
                    result.append(item_line)
                    i += 1
                    continue
                
                # Parse format: Chinese (pinyin, "english")
                match = re.match(r'^(.+?)\s+\(([^,]+),\s*"([^"]+)"\)$', item)
                if match:
                    chinese_part = match.group(1)
                    pinyin_part = match.group(2).strip()
                    english_part = match.group(3).strip()
                    result.append(f"{pad}- {chinese_part}")
                    result.append(f"{pad}  - {pinyin_part}")
                    result.append(f"{pad}  - {english_part}")
                else:
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
    parser = argparse.ArgumentParser(description='Fix breadcrumbs and component characters format')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--path', type=str, default='/Users/scobbe/src/flashcards/output')
    args = parser.parse_args()
    
    output_path = Path(args.path)
    if not output_path.exists():
        print(f"Error: {output_path} does not exist")
        sys.exit(1)
    
    md_files = [p for p in output_path.rglob('*.md') if not p.name.startswith('-')]
    
    modified_count = 0
    for md_file in md_files:
        if migrate_file(md_file, dry_run=args.dry_run):
            modified_count += 1
            action = "Would modify" if args.dry_run else "Modified"
            print(f"{action}: {md_file}")
    
    print(f"\n{'Would modify' if args.dry_run else 'Modified'} {modified_count} files out of {len(md_files)} total")
    
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

