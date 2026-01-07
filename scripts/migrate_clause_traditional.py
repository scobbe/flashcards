#!/usr/bin/env python3
"""Migrate examples to clause-by-clause traditional format.

Handles two patterns:
1. 简体句子。(繁體句子。) → 简体句子(繁體句子)。  (period before paren)
2. 秋收时，农夫割草(秋收時，農夫割草)。 → 秋收时(秋收時)，农夫割草(農夫割草)。  (clauses)

New format: each clause 简体(繁體) with period inside final paren.
"""

import json
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

    Handles:
    1. 简体。(繁體。) → 简体(繁體)。  (period before paren with period inside)
    2. 简体(繁體)。 → 简体(繁體)。   (already correct, single clause)
    3. 简A，简B(繁A，繁B)。 → 简A(繁A)，简B(繁B)。  (multi-clause)
    """
    # Pattern 1: period BEFORE paren with period inside: 简体。(繁體。)
    match = re.match(r'^(.+?)([。？！])\((.+?)[。？！]\)$', chinese)
    if match:
        simp = match.group(1)
        punct = match.group(2)
        trad = match.group(3)
        # Check if there are clause separators - if so, split them
        if any(p in simp for p in '，、；'):
            simp_parts = split_by_clause_punct(simp)
            trad_parts = split_by_clause_punct(trad)
            if len(simp_parts) == len(trad_parts):
                result = []
                for (simp_text, simp_punct), (trad_text, _) in zip(simp_parts, trad_parts):
                    result.append(f"{simp_text}({trad_text}){simp_punct}")
                return ''.join(result) + punct
        return f"{simp}({trad}){punct}"

    # Pattern 2: Check if it matches: text(text)punct (paren before period)
    match = re.match(r'^(.+?)\((.+?)\)([。？！.?!]?)$', chinese)
    if not match:
        return chinese

    simplified_full = match.group(1)
    traditional_full = match.group(2)
    ending_punct = match.group(3)

    # If they're the same, just return simplified with punct
    if simplified_full == traditional_full:
        return f"{simplified_full}({traditional_full}){ending_punct}"

    # Check if there are clause separators
    if not any(p in simplified_full for p in '，、；'):
        # Single clause - already correct format
        return chinese

    # Split both by clause punctuation
    simp_parts = split_by_clause_punct(simplified_full)
    trad_parts = split_by_clause_punct(traditional_full)

    # If different number of parts, can't match - return as-is
    if len(simp_parts) != len(trad_parts):
        return chinese

    # Build new format - show traditional for each clause
    result = []
    for (simp_text, simp_punct), (trad_text, _) in zip(simp_parts, trad_parts):
        result.append(f"{simp_text}({trad_text}){simp_punct}")

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


def migrate_cache_file(cache_path: Path, dry_run: bool = False) -> int:
    """Migrate a single cache JSON file. Returns number of changes."""
    try:
        data = json.loads(cache_path.read_text(encoding='utf-8'))
    except Exception as e:
        print(f"  [error] Failed to read {cache_path.name}: {e}")
        return 0

    changes = 0
    examples = data.get('examples', [])

    for ex in examples:
        if isinstance(ex, dict) and 'chinese' in ex:
            old_chinese = ex['chinese']
            new_chinese = convert_to_clause_format(old_chinese)
            if old_chinese != new_chinese:
                changes += 1
                if dry_run:
                    print(f"    {old_chinese}")
                    print(f"    → {new_chinese}")
                else:
                    ex['chinese'] = new_chinese

    if changes > 0 and not dry_run:
        cache_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    return changes


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Migrate examples to clause-by-clause traditional format')
    parser.add_argument('--dry-run', action='store_true', help='Show what would change without modifying')
    parser.add_argument('--path', type=str, default='/Users/scobbe/src/flashcards/output',
                        help='Path to search for files')
    args = parser.parse_args()

    output_path = Path(args.path)

    if not output_path.exists():
        print(f"Error: {output_path} does not exist")
        sys.exit(1)

    # Migrate cache files first
    cache_dir = output_path / 'chinese' / 'cache'
    cache_modified = 0
    if cache_dir.exists():
        cache_files = list(cache_dir.glob('*.json'))
        print(f"Processing {len(cache_files)} cache files...")
        for cache_file in cache_files:
            changes = migrate_cache_file(cache_file, dry_run=args.dry_run)
            if changes > 0:
                cache_modified += 1
                action = "Would modify" if args.dry_run else "Modified"
                print(f"  {action}: {cache_file.name} ({changes} examples)")
        print(f"\nCache: {'Would modify' if args.dry_run else 'Modified'} {cache_modified} files")

    # Find all markdown files (excluding combined output files)
    md_files = [p for p in output_path.rglob('*.md') if not p.name.startswith('-')]

    md_modified = 0
    print(f"\nProcessing {len(md_files)} markdown files...")
    for md_file in md_files:
        if migrate_file(md_file, dry_run=args.dry_run):
            md_modified += 1
            action = "Would modify" if args.dry_run else "Modified"
            print(f"  {action}: {md_file.name}")

    print(f"\nMarkdown: {'Would modify' if args.dry_run else 'Modified'} {md_modified} files out of {len(md_files)} total")

    # Regenerate combined output files
    if not args.dry_run and md_modified > 0:
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

