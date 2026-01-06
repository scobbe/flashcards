#!/usr/bin/env python3
"""Fix component characters and first-level sub-component breadcrumbs.

Component characters:
From: - 爻 (yáo, "trigram lines")
To:   - 爻
        - yáo
        - trigram lines

Also fixes first-level sub-components to have proper breadcrumbs.
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
    
    in_component_chars = False
    parent_english = ""
    has_breadcrumbs = False
    
    # First pass: check if already has breadcrumbs and get parent english
    for line in lines:
        if line.startswith("- **breadcrumbs:**"):
            has_breadcrumbs = True
        if line.startswith("#### "):
            parent_english = line[5:].strip()
    
    i = 0
    while i < len(lines):
        line = lines[i]
        
        # Fix H4 parent to H3 numbered format for first-level sub-components
        if line.startswith("#### ") and not has_breadcrumbs:
            parent_eng = line[5:].strip()
            # Look up parent info
            _, trad, simp, pin = find_parent_by_english(out_dir, parent_eng)
            if simp or trad:
                # Update to numbered format
                result.append(f"### 1. {parent_eng}")
                
                # Find where to insert Chinese breadcrumbs (after definition line)
                # We'll handle this in a second pass
            else:
                result.append(line)
            i += 1
            continue
        
        # Track component characters section
        if "- **component characters:**" in line:
            in_component_chars = True
            result.append(line)
            i += 1
            continue
        elif line.strip().startswith("- **") and "component characters" not in line:
            in_component_chars = False
        
        # Fix component characters format
        if in_component_chars and line.strip().startswith("- "):
            item = line.strip()[2:]  # Remove "- "
            indent = len(line) - len(line.lstrip())
            pad = " " * indent
            
            # Check if already hierarchical (next line is more indented)
            if i + 1 < len(lines) and lines[i + 1].startswith(pad + "  - "):
                result.append(line)
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
                i += 1
                continue
        
        result.append(line)
        i += 1
    
    # Second pass: add Chinese breadcrumbs for first-level sub-components
    if parent_english and not has_breadcrumbs:
        _, trad, simp, pin = find_parent_by_english(out_dir, parent_english)
        if simp or trad:
            final_result = []
            for line in result:
                final_result.append(line)
                if line.startswith("- **definition:**"):
                    crumb = f"{simp}({trad})({pin})" if pin else f"{simp}({trad})"
                    final_result.append(f"- **breadcrumbs:** {crumb}")
            result = final_result
    
    new_content = '\n'.join(result)
    
    if new_content != original:
        if not dry_run:
            file_path.write_text(new_content, encoding='utf-8')
        return True
    return False


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Fix component characters and breadcrumbs')
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

