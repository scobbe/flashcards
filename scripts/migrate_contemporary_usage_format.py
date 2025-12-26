#!/usr/bin/env python3
"""Migrate contemporary usage format from per-character to phrase-level traditional.

Old format: 又红(紅)又专(專) (pinyin, "meaning")
New format: 又红又专(又紅又專) (pinyin, "meaning")

This script finds all .md files with contemporary usage and converts them.
"""

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
OUTPUT_ROOT = PROJECT_ROOT / "output"


def convert_line(line: str) -> str:
    """Convert a single contemporary usage line from old to new format.
    
    Old: - 又红(紅)又专(專) (yòuhóngyòuzhuān, "red and expert")
    New: - 又红又专(又紅又專) (yòuhóngyòuzhuān, "red and expert")
    """
    # Match lines that have the pattern of inline traditional characters
    # Pattern: CJK(CJK) where the parenthesized char is traditional
    
    # Check if this is a contemporary usage line
    if not line.strip().startswith("- "):
        return line
    
    # Find the Chinese phrase part (before the pinyin parentheses)
    # Pattern: - PHRASE (pinyin, "meaning")
    match = re.match(r'^(\s*-\s*)(.+?)(\s*\([a-zA-Zāáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜ]+,\s*".+?"\).*)$', line)
    if not match:
        return line
    
    prefix = match.group(1)
    chinese_part = match.group(2)
    suffix = match.group(3)
    
    # Check if there are inline traditional chars like 红(紅)
    # Pattern: simplified(traditional) where both are single CJK chars
    inline_pattern = r'([\u4e00-\u9fff])\(([\u4e00-\u9fff])\)'
    
    if not re.search(inline_pattern, chinese_part):
        return line  # No inline traditional, leave as is
    
    # Extract simplified and traditional versions
    simplified = re.sub(inline_pattern, r'\1', chinese_part)
    traditional = re.sub(inline_pattern, r'\2', chinese_part)
    
    # If simplified and traditional are the same after extraction, no change needed
    if simplified == traditional:
        return line
    
    # Build new format: simplified(traditional) (pinyin, "meaning")
    new_chinese = f"{simplified}({traditional})"
    new_line = f"{prefix}{new_chinese}{suffix}"
    
    return new_line


def process_file(md_path: Path, dry_run: bool = False) -> int:
    """Process a single markdown file. Returns number of lines changed."""
    text = md_path.read_text(encoding="utf-8")
    lines = text.split("\n")
    
    changes = 0
    new_lines = []
    in_contemporary = False
    
    for line in lines:
        # Track if we're in contemporary usage section
        if "**contemporary usage:**" in line.lower():
            in_contemporary = True
            new_lines.append(line)
            continue
        
        # End of contemporary usage section (next field or divider)
        if in_contemporary and (line.startswith("- **") or line.strip() == "---" or line.strip() == "%%%"):
            in_contemporary = False
        
        if in_contemporary and line.strip().startswith("- "):
            new_line = convert_line(line)
            if new_line != line:
                changes += 1
                if not dry_run:
                    print(f"  {line.strip()}")
                    print(f"  → {new_line.strip()}")
            new_lines.append(new_line)
        else:
            new_lines.append(line)
    
    if changes > 0 and not dry_run:
        md_path.write_text("\n".join(new_lines), encoding="utf-8")
    
    return changes


def find_md_files(root: Path) -> list[Path]:
    """Find all .md files that might have contemporary usage."""
    return list(root.rglob("*.md"))


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Migrate contemporary usage format")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be changed")
    args = parser.parse_args()
    
    md_files = find_md_files(OUTPUT_ROOT)
    print(f"Found {len(md_files)} .md files to check\n")
    
    total_changes = 0
    files_changed = 0
    
    for md_path in md_files:
        # Skip output.md aggregation files
        if md_path.name == "-output.md":
            continue
        
        changes = process_file(md_path, dry_run=args.dry_run)
        if changes > 0:
            files_changed += 1
            total_changes += changes
            if args.dry_run:
                print(f"[would change] {md_path.relative_to(PROJECT_ROOT)} ({changes} lines)")
            else:
                print(f"[changed] {md_path.relative_to(PROJECT_ROOT)} ({changes} lines)")
    
    print(f"\n{'[dry-run] ' if args.dry_run else ''}Total: {total_changes} lines in {files_changed} files")


if __name__ == "__main__":
    main()

