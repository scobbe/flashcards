#!/usr/bin/env python3
"""Fix cards where pinyin and english are combined on one line.

From:
  - 昌
    - chāng, prosperous

To:
  - 昌
    - chāng
    - prosperous
"""

import re
import sys
from pathlib import Path


def is_pinyin_line(line: str) -> bool:
    """Check if a line looks like 'pinyin, english' combined."""
    # Must start with 4 spaces and a dash
    if not line.startswith("    - "):
        return False
    
    content = line[6:]  # Remove "    - "
    
    # Check if it has the pattern: pinyin, english
    # Pinyin will have tone marks or be short romanization
    # Pattern: short word with possible tone marks, comma, then english
    match = re.match(r'^([a-zA-Zāáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜ]+),\s+(.+)$', content)
    if match:
        pinyin = match.group(1)
        english = match.group(2)
        # Pinyin should be short (typically 1-6 chars) and english should be words
        if len(pinyin) <= 8 and not pinyin[0].isupper():
            return True
    return False


def split_pinyin_english(line: str) -> tuple:
    """Split a combined pinyin,english line into two lines."""
    content = line[6:]  # Remove "    - "
    match = re.match(r'^([a-zA-Zāáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜ]+),\s+(.+)$', content)
    if match:
        pinyin = match.group(1)
        english = match.group(2)
        return f"    - {pinyin}", f"    - {english}"
    return line, None


def migrate_file(file_path: Path, dry_run: bool = False) -> bool:
    """Migrate a single markdown file."""
    content = file_path.read_text(encoding='utf-8')
    original = content
    
    lines = content.split('\n')
    result = []
    
    in_characters = False
    
    for i, line in enumerate(lines):
        # Track characters section
        if line.strip() == "- **characters:**":
            in_characters = True
            result.append(line)
            continue
        elif line.strip().startswith("- **") and "characters" not in line:
            in_characters = False
        
        if in_characters and is_pinyin_line(line):
            # Check if next line exists and is NOT indented at same level
            # (meaning there's no separate english line)
            next_is_english = False
            if i + 1 < len(lines):
                next_line = lines[i + 1]
                # If next line is at same indentation and looks like english only
                if next_line.startswith("    - ") and not is_pinyin_line(next_line):
                    # Check if next line content doesn't look like pinyin
                    next_content = next_line[6:]
                    if not re.match(r'^[a-zA-Zāáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜ]+$', next_content.split(',')[0].split(';')[0].strip()):
                        next_is_english = True
            
            if not next_is_english:
                # Split this line
                pinyin_line, english_line = split_pinyin_english(line)
                result.append(pinyin_line)
                if english_line:
                    result.append(english_line)
                continue
        
        result.append(line)
    
    new_content = '\n'.join(result)
    
    if new_content != original:
        if not dry_run:
            file_path.write_text(new_content, encoding='utf-8')
        return True
    return False


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Fix pinyin/english combined lines')
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

