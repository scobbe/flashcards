#!/usr/bin/env python3
"""Migrate sublists to hierarchical format.

Contemporary usage:
From: 六月: liù yuè; June
To:   - 六月
        - liù yuè
        - June

Description (convert inline to multi-line with arrows split):
From: - **description:** semantic: 上 (shàng, "up") → phonetic: 班 (bān, "shift").
To:   - **description:**
        - semantic: 上 (shàng, "up") →
        - phonetic: 班 (bān, "shift")
"""

import re
import sys
from pathlib import Path


def migrate_file(file_path: Path, dry_run: bool = False) -> bool:
    """Migrate a single markdown file."""
    content = file_path.read_text(encoding='utf-8')
    original = content
    
    lines = content.split('\n')
    result = []
    
    in_contemporary = False
    i = 0
    
    while i < len(lines):
        line = lines[i]
        
        # Track contemporary usage section
        if line.strip() == "- **contemporary usage:**":
            in_contemporary = True
            result.append(line)
            i += 1
            continue
        elif line.strip().startswith("- **") and "contemporary usage" not in line:
            in_contemporary = False
        
        # Convert contemporary usage items to hierarchical
        if in_contemporary and line.startswith("  - ") and ": " in line and "; " in line:
            item = line[4:]  # Remove "  - "
            # Check if already hierarchical (next line is indented more)
            if i + 1 < len(lines) and lines[i + 1].startswith("    - "):
                # Already hierarchical, skip
                result.append(line)
                i += 1
                continue
            
            # Parse and convert
            if ": " in item:
                chinese_part, rest = item.split(": ", 1)
                if "; " in rest:
                    pinyin_part, english_part = rest.split("; ", 1)
                    result.append(f"  - {chinese_part}")
                    result.append(f"    - {pinyin_part}")
                    if english_part:
                        result.append(f"    - {english_part}")
                    i += 1
                    continue
        
        # Convert inline description to multi-line with arrow splitting
        match = re.match(r'^(\s*)- \*\*description:\*\* (.+)$', line)
        if match:
            indent = match.group(1)
            description = match.group(2).strip()
            
            result.append(f"{indent}- **description:**")
            
            if " → " in description:
                # Split on arrows into separate bullets
                arrow_parts = description.split(" → ")
                for j, ap in enumerate(arrow_parts):
                    ap = ap.rstrip('.')
                    if j < len(arrow_parts) - 1:
                        result.append(f"{indent}  - {ap} →")
                    else:
                        result.append(f"{indent}  - {ap}")
            else:
                # Single bullet
                description = description.rstrip('.')
                result.append(f"{indent}  - {description}")
            
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
    parser = argparse.ArgumentParser(description='Migrate sublists to hierarchical format')
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

