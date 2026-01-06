#!/usr/bin/env python3
"""Undo the clause-by-clause traditional format, reverting to full-sentence format.

The previous migration converted:
  我们坐着工作，效率反而更高(我們坐著工作，效率反而更高)。
To:
  我们坐着工作(我們坐著工作)，效率反而更高。

This script converts BACK to the original format (full sentence traditional in parentheses).
"""

import re
import sys
from pathlib import Path


def convert_back_to_sentence_format(chinese: str) -> str:
    """Convert clause-level traditional annotations back to sentence-level.
    
    From: 我们坐着工作(我們坐著工作)，效率反而更高。
    To:   我们坐着工作，效率反而更高(我們坐著工作，效率反而更高)。
    """
    # Find all clause(traditional) patterns
    # Pattern: text(parenthesized_text) followed by punctuation or end
    pattern = r'([^\(]+?)\(([^\)]+)\)([，、；,;。？！.?!]?)'
    
    matches = list(re.finditer(pattern, chinese))
    if not matches:
        return chinese
    
    # Extract ending punctuation
    ending_punct = ''
    if chinese and chinese[-1] in '。？！.?!':
        ending_punct = chinese[-1]
    
    # Build simplified and traditional versions
    simplified_parts = []
    traditional_parts = []
    last_end = 0
    
    for m in matches:
        # Add any text before this match
        before = chinese[last_end:m.start()]
        simplified_parts.append(before)
        traditional_parts.append(before)
        
        simp_clause = m.group(1)
        trad_clause = m.group(2)
        punct = m.group(3)
        
        simplified_parts.append(simp_clause + punct)
        traditional_parts.append(trad_clause + punct)
        
        last_end = m.end()
    
    # Add remaining text after last match
    remaining = chinese[last_end:]
    # Remove ending punct if we already captured it
    if remaining and remaining[-1] in '。？！.?!' and ending_punct:
        remaining = remaining[:-1]
    simplified_parts.append(remaining)
    traditional_parts.append(remaining)
    
    simplified_full = ''.join(simplified_parts)
    traditional_full = ''.join(traditional_parts)
    
    # Remove trailing punctuation from both before combining
    for punct in '。？！.?!':
        simplified_full = simplified_full.rstrip(punct)
        traditional_full = traditional_full.rstrip(punct)
    
    # If they're the same, no need for traditional
    if simplified_full == traditional_full:
        return simplified_full + ending_punct
    
    return f"{simplified_full}({traditional_full}){ending_punct}"


def migrate_file(file_path: Path, dry_run: bool = False) -> bool:
    """Migrate a single markdown file back to sentence-level format.
    
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
            
            # Only process if has clause(traditional) pattern but NOT character-level
            # Clause-level: 我们坐着工作(我們坐著工作)，
            # Character-level would be: 们(們) - single char before paren
            if re.search(r'[^\(]{2,}\([^\)]+\)[，、；,;。？！.?!]', chinese):
                new_chinese = convert_back_to_sentence_format(chinese)
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
    parser = argparse.ArgumentParser(description='Undo clause-by-clause traditional format')
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
