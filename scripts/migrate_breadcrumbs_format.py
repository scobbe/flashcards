#!/usr/bin/env python3
"""Update breadcrumbs to new format with traditional and pinyin.

Front (English): numbered list like "1. Na (female name) / 2. That"
Back (Chinese): "娜(娜)(nà) > 那(那)(nà)" format
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


def is_cjk_char(ch: str) -> bool:
    """Check if a character is CJK."""
    return len(ch) == 1 and '\u4e00' <= ch <= '\u9fff'


def build_breadcrumbs(out_dir: Path, word: str) -> tuple:
    """Build English and Chinese breadcrumb chains from the word/filename."""
    parts = word.split(".")
    if len(parts) < 3:
        return [], []
    
    all_chinese = []
    for p in parts[1:]:
        if len(p) == 1 and is_cjk_char(p):
            all_chinese.append(p)
    
    if len(all_chinese) < 2:
        return [], []
    
    ancestor_chars = all_chinese[:-1]
    
    english_crumbs = []
    chinese_crumbs = []  # (simplified, traditional, pinyin)
    prefix = parts[0]
    
    for i, ch in enumerate(ancestor_chars):
        if i == 0:
            md_path = out_dir / f"{prefix}.{ch}.md"
        else:
            chain = ".".join(ancestor_chars[:i+1])
            md_path = out_dir / f"{prefix}.{chain}.md"
        
        eng, trad, simp, pin = extract_card_info(md_path)
        english_crumbs.append(eng if eng else ch)
        chinese_crumbs.append((simp or ch, trad or ch, pin or ""))
    
    return english_crumbs, chinese_crumbs


def migrate_file(file_path: Path, dry_run: bool = False) -> bool:
    """Migrate a single markdown file."""
    content = file_path.read_text(encoding='utf-8')
    original = content
    
    lines = content.split('\n')
    result = []
    
    # Get word from filename
    word = file_path.stem
    out_dir = file_path.parent
    
    # Build new breadcrumbs
    english_crumbs, chinese_crumbs = build_breadcrumbs(out_dir, word)
    
    i = 0
    while i < len(lines):
        line = lines[i]
        
        # Update H3 or H4 breadcrumbs on front (English)
        if (line.startswith("### ") or line.startswith("#### ")) and english_crumbs:
            prefix = "### " if line.startswith("### ") else "#### "
            old_content = line[len(prefix):]
            # Check if this looks like breadcrumbs (contains > or numbered format)
            if " > " in old_content or re.match(r'^\d+\.', old_content):
                # Replace with new numbered format
                numbered_lines = [f"{j+1}. {eng}" for j, eng in enumerate(english_crumbs)]
                line = f"### {' / '.join(numbered_lines)}"  # Always use H3 for consistency
        
        # Update Chinese breadcrumbs on back
        if line.startswith("- **breadcrumbs:**") and chinese_crumbs:
            crumb_strs = []
            for simp, trad, pin in chinese_crumbs:
                crumb = f"{simp}({trad})({pin})" if pin else f"{simp}({trad})"
                crumb_strs.append(crumb)
            breadcrumb_str = " > ".join(crumb_strs)
            line = f"- **breadcrumbs:** {breadcrumb_str}"
        
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
    parser = argparse.ArgumentParser(description='Update breadcrumbs format')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--path', type=str, default='/Users/scobbe/src/flashcards/output')
    args = parser.parse_args()
    
    output_path = Path(args.path)
    if not output_path.exists():
        print(f"Error: {output_path} does not exist")
        sys.exit(1)
    
    # Find files with breadcrumbs (sub-component files typically have 3+ dots in name)
    md_files = [p for p in output_path.rglob('*.md') 
                if not p.name.startswith('-') and p.stem.count('.') >= 2]
    
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

