#!/usr/bin/env python3
"""Migrate cache files from old format to new format.

Old format:
- -output.cache.json: {"words": [{"base": "1.得", "md": "hash"}, ...]}
- 1.得.cache.json: {"children": [{"base": "1.得.又", "md": "hash"}, ...]}

New format:
- 1.得.cache.json: {"md": "hash", "children": [{"base": "1.得.又", "md": "hash"}, ...]}
- No -output.cache.json

This script:
1. Reads -output.cache.json to get head MD hashes
2. Merges them into per-card cache files
3. Deletes -output.cache.json
"""

import argparse
import json
from pathlib import Path


def migrate_folder(folder: Path, verbose: bool = False, dry_run: bool = False) -> int:
    """Migrate cache files in a folder.
    
    Returns the number of changes made.
    """
    global_cache_path = folder / "-output.cache.json"
    if not global_cache_path.exists():
        return 0
    
    changes = 0
    
    # Load global cache
    try:
        global_data = json.loads(global_cache_path.read_text(encoding="utf-8"))
        words = global_data.get("words", [])
        if not isinstance(words, list):
            words = []
    except Exception as e:
        if verbose:
            print(f"  [error] Failed to read {global_cache_path}: {e}")
        return 0
    
    # Build lookup: base -> md hash
    head_hashes = {}
    for w in words:
        if isinstance(w, dict):
            base = w.get("base")
            md = w.get("md")
            if isinstance(base, str) and isinstance(md, str):
                head_hashes[base] = md
    
    if verbose:
        print(f"  [info] Found {len(head_hashes)} head hashes in -output.cache.json")
    
    # Merge into per-card caches
    for base, md_hash in head_hashes.items():
        card_cache_path = folder / f"{base}.cache.json"
        
        # Load existing per-card cache (if any)
        if card_cache_path.exists():
            try:
                card_data = json.loads(card_cache_path.read_text(encoding="utf-8"))
                if not isinstance(card_data, dict):
                    card_data = {}
            except Exception:
                card_data = {}
        else:
            card_data = {}
        
        # Add/update the md hash
        old_md = card_data.get("md", "")
        if old_md != md_hash:
            card_data["md"] = md_hash
            
            # Ensure children field exists
            if "children" not in card_data:
                card_data["children"] = []
            
            if not dry_run:
                card_cache_path.write_text(
                    json.dumps(card_data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8"
                )
            
            if verbose:
                action = "[dry-run]" if dry_run else "[updated]"
                print(f"  {action} {card_cache_path.name}")
            changes += 1
    
    # Delete global cache
    if not dry_run:
        global_cache_path.unlink()
    
    if verbose:
        action = "[dry-run]" if dry_run else "[deleted]"
        print(f"  {action} -output.cache.json")
    changes += 1
    
    return changes


def main():
    parser = argparse.ArgumentParser(description="Migrate cache files to new format")
    parser.add_argument(
        "--root",
        type=str,
        default="output",
        help="Root directory to scan (default: output)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose output",
    )
    args = parser.parse_args()
    
    root = Path(args.root)
    if not root.exists():
        print(f"[error] Root directory does not exist: {root}")
        return 1
    
    # Find all -output.cache.json files
    cache_files = list(root.rglob("-output.cache.json"))
    
    if not cache_files:
        print("[info] No -output.cache.json files found - nothing to migrate")
        return 0
    
    print(f"[info] Found {len(cache_files)} folders to migrate")
    if args.dry_run:
        print("[info] DRY RUN - no changes will be made")
    
    total_changes = 0
    for cache_file in sorted(cache_files):
        folder = cache_file.parent
        if args.verbose:
            print(f"\n📂 {folder}")
        changes = migrate_folder(folder, verbose=args.verbose, dry_run=args.dry_run)
        total_changes += changes
    
    print(f"\n[done] {'Would make' if args.dry_run else 'Made'} {total_changes} changes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

