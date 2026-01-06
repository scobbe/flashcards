#!/usr/bin/env python3
"""Audit all flashcards in the repo for missing fields.

Checks for:
- Missing etymology (all cards should have one)
- Missing character breakdowns (multi-character words should have them)
- Sparse character definitions (should have multiple meanings)

Usage:
    python scripts/audit_cards.py [--fix]
    
    --fix: Clear manifests for directories with issues so they can be regenerated
"""

import sys
import re
from pathlib import Path
from typing import Dict, List, Set, Tuple

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.common.utils import is_cjk_char


def count_cjk_chars(text: str) -> int:
    """Count CJK characters in text."""
    return sum(1 for ch in text if is_cjk_char(ch))


def parse_card(content: str) -> Dict[str, any]:
    """Parse a card's markdown content and extract fields."""
    result = {
        "has_etymology": False,
        "has_origin": False,  # For English cards
        "has_characters": False,
        "has_examples": False,
        "headword": "",
        "char_count": 0,
        "char_definitions_sparse": False,
        "is_english_card": False,
    }
    
    # Extract headword from ## line
    headword_match = re.search(r'^## (.+)$', content, re.MULTILINE)
    if headword_match:
        headword = headword_match.group(1).strip()
        # Remove traditional in parentheses for counting
        headword_simple = re.sub(r'\([^)]+\)', '', headword)
        result["headword"] = headword
        result["char_count"] = count_cjk_chars(headword_simple)
    
    # Check for etymology (Chinese cards)
    result["has_etymology"] = bool(re.search(r'^\s*-\s*\*\*etymology:\*\*', content, re.MULTILINE))
    
    # Check for origin (English cards)
    result["has_origin"] = bool(re.search(r'^\s*-\s*\*\*origin:\*\*', content, re.MULTILINE))
    
    # Detect if this is an English card (has origin field or no CJK characters)
    result["is_english_card"] = result["has_origin"] or result["char_count"] == 0
    
    # Check for characters section
    result["has_characters"] = bool(re.search(r'^\s*-\s*\*\*characters:\*\*', content, re.MULTILINE))
    
    # Check for examples
    result["has_examples"] = bool(re.search(r'^\s*-\s*\*\*examples:\*\*', content, re.MULTILINE))
    
    # Check if character definitions are sparse (only one word)
    # Look for patterns like "    - single_word" under characters
    char_section = re.search(r'-\s*\*\*characters:\*\*(.*?)(?=-\s*\*\*|%%%|$)', content, re.DOTALL)
    if char_section:
        char_content = char_section.group(1)
        # Find all english definition lines (third level indent, not pinyin)
        # Pattern: lines that are english definitions under character breakdowns
        eng_lines = re.findall(r'^    - ([^-\n]+)$', char_content, re.MULTILINE)
        sparse_count = 0
        for line in eng_lines:
            line = line.strip()
            # Skip if it looks like pinyin (contains tone marks or is very short)
            if any(c in line for c in 'āáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜ'):
                continue
            # Check if it's sparse (no semicolons, no commas, single word)
            if ';' not in line and ',' not in line and ' ' not in line:
                sparse_count += 1
        if sparse_count > 0:
            result["char_definitions_sparse"] = True
    
    return result


def audit_directory(output_dir: Path) -> Tuple[int, int, List[str]]:
    """Audit all cards in a directory.
    
    Returns (total_cards, issues_found, issue_descriptions).
    """
    issues: List[str] = []
    total = 0
    
    for md_file in sorted(output_dir.glob("*.md")):
        # Skip output files
        if md_file.name.startswith("-"):
            continue
        
        total += 1
        content = md_file.read_text(encoding="utf-8")
        card = parse_card(content)
        
        file_issues = []
        
        # Check for missing etymology/origin based on card type
        if card["is_english_card"]:
            # English cards should have origin
            if not card["has_origin"]:
                file_issues.append("missing origin")
        else:
            # Chinese cards should have etymology
            if not card["has_etymology"]:
                file_issues.append("missing etymology")
            
            # Check for missing character breakdown on multi-char words
            if card["char_count"] > 1 and not card["has_characters"]:
                file_issues.append("missing character breakdown")
            
            # Check for sparse character definitions
            if card["has_characters"] and card["char_definitions_sparse"]:
                file_issues.append("sparse char definitions")
        
        if file_issues:
            issues.append(f"{md_file.name}: {', '.join(file_issues)}")
    
    return total, len(issues), issues


def find_all_output_dirs(root: Path) -> List[Path]:
    """Find all output directories containing flashcards."""
    output_dirs = []
    
    for output_dir in root.rglob("output"):
        if output_dir.is_dir():
            # Check if it has .md files (not just the combined output)
            md_files = [f for f in output_dir.glob("*.md") if not f.name.startswith("-")]
            if md_files:
                output_dirs.append(output_dir)
    
    return sorted(output_dirs)


def main():
    fix_mode = "--fix" in sys.argv
    
    project_root = Path(__file__).parent.parent
    output_root = project_root / "output"
    
    if not output_root.exists():
        print(f"Error: output directory not found: {output_root}")
        sys.exit(1)
    
    # Find all output directories
    output_dirs = find_all_output_dirs(output_root)
    
    print(f"Found {len(output_dirs)} output directories to audit\n")
    
    total_cards = 0
    total_issues = 0
    dirs_with_issues: List[Tuple[Path, int, int, List[str]]] = []
    
    for output_dir in output_dirs:
        cards, issues, issue_list = audit_directory(output_dir)
        total_cards += cards
        total_issues += issues
        
        if issues > 0:
            dirs_with_issues.append((output_dir, cards, issues, issue_list))
    
    # Summary
    print("=" * 70)
    print("AUDIT SUMMARY")
    print("=" * 70)
    print(f"Total cards audited: {total_cards}")
    print(f"Total issues found: {total_issues}")
    print(f"Directories with issues: {len(dirs_with_issues)}")
    print()
    
    if dirs_with_issues:
        print("DIRECTORIES NEEDING REGENERATION:")
        print("-" * 70)
        for output_dir, cards, issues, issue_list in dirs_with_issues:
            rel_path = output_dir.relative_to(project_root)
            pct = (issues / cards) * 100 if cards > 0 else 0
            print(f"\n📁 {rel_path}")
            print(f"   Cards: {cards}, Issues: {issues} ({pct:.0f}%)")
            
            # Show first few issues as examples
            for issue in issue_list[:3]:
                print(f"   • {issue}")
            if len(issue_list) > 3:
                print(f"   ... and {len(issue_list) - 3} more")
        
        print("\n" + "=" * 70)
        
        if fix_mode:
            print("\nFIXING: Clearing manifests for affected directories...")
            from lib.common.manifest import load_output_manifest, save_output_manifest
            
            for output_dir, cards, issues, issue_list in dirs_with_issues:
                manifest = load_output_manifest(output_dir)
                file_status = manifest.get("file_status", {})
                # Mark all as incomplete
                new_status = {word: False for word in file_status.keys()}
                save_output_manifest(output_dir, new_status)
                
                # Delete existing card files
                deleted = 0
                for md_file in output_dir.glob("*.md"):
                    if not md_file.name.startswith("-"):
                        md_file.unlink()
                        deleted += 1
                
                rel_path = output_dir.relative_to(project_root)
                print(f"   ✓ Cleared {rel_path} ({deleted} files)")
            
            print("\nRun the generator on each directory to regenerate cards.")
            print("\nExample commands:")
            for output_dir, _, _, _ in dirs_with_issues[:3]:
                input_dir = output_dir.parent / "input"
                config_path = input_dir / "-config.json"
                if config_path.exists():
                    rel_config = config_path.relative_to(project_root)
                    print(f"  .venv/bin/python generate.py --config {rel_config} --verbose")
        else:
            print("\nTo fix these issues, run:")
            print("  python scripts/audit_cards.py --fix")
            print("\nThen regenerate each directory with the generator.")
    else:
        print("✅ All cards pass audit!")


if __name__ == "__main__":
    main()

