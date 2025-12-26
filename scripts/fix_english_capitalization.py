#!/usr/bin/env python3
"""Fix capitalization in existing English output directory.

Capitalizes the first letter of the word in:
1. The ## heading in each .md file
2. The -output.md combined file
3. The -input.parsed.csv file

Usage:
    python scripts/fix_english_capitalization.py /path/to/output/dir
"""

import re
import sys
from pathlib import Path


def capitalize_first(s: str) -> str:
    """Capitalize the first letter of a string."""
    if not s:
        return s
    return s[0].upper() + s[1:] if len(s) > 1 else s.upper()


def fix_md_file(path: Path) -> bool:
    """Fix the ## heading in a markdown file. Returns True if changed."""
    content = path.read_text(encoding="utf-8")
    
    # Match ## heading at the start
    match = re.match(r'^## (.+)$', content, re.MULTILINE)
    if not match:
        return False
    
    word = match.group(1)
    capitalized = capitalize_first(word)
    
    if word == capitalized:
        return False
    
    new_content = re.sub(r'^## .+$', f'## {capitalized}', content, count=1, flags=re.MULTILINE)
    path.write_text(new_content, encoding="utf-8")
    return True


def fix_csv_file(path: Path) -> int:
    """Fix capitalization in CSV file. Returns count of changed lines."""
    lines = path.read_text(encoding="utf-8").splitlines()
    changed = 0
    new_lines = []
    
    for line in lines:
        if line.strip():
            capitalized = capitalize_first(line)
            if capitalized != line:
                changed += 1
            new_lines.append(capitalized)
        else:
            new_lines.append(line)
    
    if changed > 0:
        path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    
    return changed


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/fix_english_capitalization.py /path/to/output/dir")
        sys.exit(1)
    
    output_dir = Path(sys.argv[1])
    if not output_dir.exists():
        print(f"Error: Directory not found: {output_dir}")
        sys.exit(1)
    
    print(f"Fixing capitalization in: {output_dir}")
    
    # Fix individual .md files
    md_fixed = 0
    for md_file in output_dir.glob("*.md"):
        if md_file.name.startswith("-"):
            continue
        if fix_md_file(md_file):
            print(f"  Fixed: {md_file.name}")
            md_fixed += 1
    
    print(f"Fixed {md_fixed} markdown files")
    
    # Fix -input.parsed.csv
    csv_path = output_dir / "-input.parsed.csv"
    if csv_path.exists():
        csv_fixed = fix_csv_file(csv_path)
        print(f"Fixed {csv_fixed} lines in -input.parsed.csv")
    
    # Regenerate -output.md from individual files
    output_md = output_dir / "-output.md"
    md_files = sorted(
        [p for p in output_dir.glob("*.md") if not p.name.startswith("-")],
        key=lambda p: (int(p.name.split(".")[0]) if p.name.split(".")[0].isdigit() else 999, p.name)
    )
    
    parts = []
    for p in md_files:
        parts.append(p.read_text(encoding="utf-8", errors="ignore"))
    
    output_md.write_text("\n\n".join(parts) + ("\n" if parts else ""), encoding="utf-8")
    print(f"Regenerated -output.md with {len(md_files)} files")
    
    print("Done!")


if __name__ == "__main__":
    main()

