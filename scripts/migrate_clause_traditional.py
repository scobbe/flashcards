#!/usr/bin/env python3
"""Migrate examples to clause-by-clause traditional format.

From: 我们坐着工作，效率反而更高(我們坐著工作，效率反而更高)。
To:   我们坐着工作(我們坐著工作)，效率反而更高。

Shows traditional in parentheses for each clause that differs.
"""

import re
import sys
from pathlib import Path


def split_by_clause_punct(text: str) -> list:
    """Split text by Chinese clause punctuation, keeping the punctuation.
    
    Returns list of (clause_text, punctuation) tuples.
    """
    # Split by common Chinese clause separators
    pattern = r'([，、；,;])'
    parts = re.split(pattern, text)
    
    # Combine text with its following punctuation
    result = []
    i = 0
    while i < len(parts):
        if i + 1 < len(parts) and re.match(r'^[，、；,;]$', parts[i + 1]):
            result.append((parts[i], parts[i + 1]))
            i += 2
        else:
            result.append((parts[i], ''))
            i += 1
    return result


def convert_to_clause_format(chinese: str) -> str:
    """Convert from full-sentence traditional to clause-by-clause format.
    
    From: 简体全文(繁体全文)。
    To:   简体1(繁体1)，简体2。 (only show trad where clause differs)
    """
    # Check if it matches the full-sentence format: text(text)punct
    match = re.match(r'^(.+?)\((.+?)\)([。？！.?!]?)$', chinese)
    if not match:
        return chinese
    
    simplified_full = match.group(1)
    traditional_full = match.group(2)
    ending_punct = match.group(3)
    
    # If they're the same, just return simplified
    if simplified_full == traditional_full:
        return simplified_full + ending_punct
    
    # Split both by clause punctuation
    simp_parts = split_by_clause_punct(simplified_full)
    trad_parts = split_by_clause_punct(traditional_full)
    
    # If different number of parts, can't match - return as-is
    if len(simp_parts) != len(trad_parts):
        return chinese
    
    # Build new format - show traditional for each clause that differs
    result = []
    for (simp_text, simp_punct), (trad_text, _) in zip(simp_parts, trad_parts):
        if simp_text != trad_text:
            # This clause differs, show traditional
            result.append(f"{simp_text}({trad_text}){simp_punct}")
        else:
            # Same, no need for traditional
            result.append(f"{simp_text}{simp_punct}")
    
    return ''.join(result) + ending_punct


def migrate_file(file_path: Path, dry_run: bool = False) -> bool:
    """Migrate a single markdown file.
    
    Returns True if file was modified.
    """
    content = file_path.read_text(encoding='utf-8')
    original = content
    
    lines = content.split('\n')
    result = []
    
    in_examples = False
    
    for i, line in enumerate(lines):
        # Track examples section
        if line.strip() == "- **examples:**":
            in_examples = True
            result.append(line)
            continue
        elif line.strip().startswith("- **") and "examples" not in line:
            in_examples = False
        
        # Check for Chinese example lines (first line of hierarchical example)
        if in_examples and line.startswith("  - ") and not line.startswith("  - **"):
            chinese = line[4:]  # Remove "  - "
            
            # Check if next lines are pinyin and english (hierarchical format)
            if i + 1 < len(lines) and lines[i + 1].startswith("    - "):
                # This is hierarchical format, try to convert the Chinese
                new_chinese = convert_to_clause_format(chinese)
                if new_chinese != chinese:
                    line = f"  - {new_chinese}"
        
        result.append(line)
    
    new_content = '\n'.join(result)
    
    if new_content != original:
        if not dry_run:
            file_path.write_text(new_content, encoding='utf-8')
        return True
    return False


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Migrate examples to clause-by-clause traditional format')
    parser.add_argument('--dry-run', action='store_true', help='Show what would change without modifying')
    parser.add_argument('--path', type=str, default='/Users/scobbe/src/flashcards/output',
                        help='Path to search for markdown files')
    args = parser.parse_args()
    
    output_path = Path(args.path)
    
    if not output_path.exists():
        print(f"Error: {output_path} does not exist")
        sys.exit(1)
    
    # Find all markdown files (excluding combined output files)
    md_files = [p for p in output_path.rglob('*.md') if not p.name.startswith('-')]
    
    modified_count = 0
    for md_file in md_files:
        if migrate_file(md_file, dry_run=args.dry_run):
            modified_count += 1
            action = "Would modify" if args.dry_run else "Modified"
            print(f"{action}: {md_file}")
    
    print(f"\n{'Would modify' if args.dry_run else 'Modified'} {modified_count} files out of {len(md_files)} total")
    
    # Regenerate combined output files
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

