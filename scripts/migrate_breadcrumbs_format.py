#!/usr/bin/env python3
"""Migrate sub-component headings to new breadcrumb format.

Old format:
### 门(門)
#### 西门町 → 门

New format:
### 西门町(西門町) → 门(門)

Each breadcrumb element includes its traditional form in parentheses.
"""

import json
import re
import sys
from pathlib import Path


# Cache for traditional lookups
TRAD_CACHE = {}


def load_traditional_from_cache(cache_dir: Path) -> None:
    """Load simplified->traditional mappings from cache files."""
    if not cache_dir.exists():
        return

    for cache_file in cache_dir.glob('*.json'):
        try:
            data = json.loads(cache_file.read_text(encoding='utf-8'))
            simp = data.get('simplified', '')
            trad = data.get('traditional', '')
            if simp and trad:
                TRAD_CACHE[simp] = trad
        except Exception:
            pass


def get_traditional(simplified: str) -> str:
    """Get traditional form from cache, or return simplified if not found."""
    return TRAD_CACHE.get(simplified, simplified)


def format_with_trad(simplified: str) -> str:
    """Format a word with its traditional in parens if different."""
    trad = get_traditional(simplified)
    if trad and trad != simplified:
        return f"{simplified}({trad})"
    return simplified


def migrate_file(file_path: Path, dry_run: bool = False) -> int:
    """Migrate a single markdown file. Returns number of changes."""
    content = file_path.read_text(encoding='utf-8')
    original = content

    lines = content.split('\n')
    result = []
    changes = 0

    i = 0
    while i < len(lines):
        line = lines[i]

        # Look for pattern: ### X(Y) followed by #### breadcrumb → X
        if line.startswith('### ') and i + 1 < len(lines) and lines[i + 1].startswith('#### '):
            # Extract current character with traditional from H3
            h3_match = re.match(r'^### (.+?)(?:\((.+?)\))?$', line)
            breadcrumb_line = lines[i + 1]
            breadcrumb_match = re.match(r'^#### (.+)$', breadcrumb_line)

            if h3_match and breadcrumb_match:
                current_simp = h3_match.group(1)
                current_trad = h3_match.group(2) or current_simp
                breadcrumb_text = breadcrumb_match.group(1)

                # Parse breadcrumb: 西门町 → 门 → 口
                parts = [p.strip() for p in breadcrumb_text.split(' → ')]

                # Build new breadcrumb with traditional forms
                new_parts = []
                for part in parts[:-1]:  # All except the last (current char)
                    new_parts.append(format_with_trad(part))

                # Add current character with its known traditional
                if current_trad != current_simp:
                    new_parts.append(f"{current_simp}({current_trad})")
                else:
                    new_parts.append(current_simp)

                new_heading = '### ' + ' → '.join(new_parts)
                result.append(new_heading)
                changes += 1
                i += 2  # Skip both the ### and #### lines
                continue

        result.append(line)
        i += 1

    new_content = '\n'.join(result)

    if new_content != original:
        if not dry_run:
            file_path.write_text(new_content, encoding='utf-8')
        return changes
    return 0


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Migrate sub-component headings to new breadcrumb format')
    parser.add_argument('--dry-run', action='store_true', help='Show what would change without modifying')
    parser.add_argument('--path', type=str, default='/Users/scobbe/src/flashcards/output',
                        help='Path to search for files')
    args = parser.parse_args()

    output_path = Path(args.path)

    if not output_path.exists():
        print(f"Error: {output_path} does not exist")
        sys.exit(1)

    # Load traditional mappings from cache
    cache_dir = output_path / 'chinese' / 'cache'
    print("Loading traditional mappings from cache...")
    load_traditional_from_cache(cache_dir)
    print(f"Loaded {len(TRAD_CACHE)} mappings")

    # Find all markdown files (excluding combined output files)
    md_files = [p for p in output_path.rglob('*.md') if not p.name.startswith('-')]

    modified_count = 0
    total_changes = 0
    print(f"\nProcessing {len(md_files)} markdown files...")

    for md_file in md_files:
        changes = migrate_file(md_file, dry_run=args.dry_run)
        if changes > 0:
            modified_count += 1
            total_changes += changes
            action = "Would modify" if args.dry_run else "Modified"
            print(f"  {action}: {md_file.name} ({changes} headings)")

    print(f"\n{'Would modify' if args.dry_run else 'Modified'} {modified_count} files ({total_changes} headings)")

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

