#!/usr/bin/env python3
"""Clear output manifest to force regeneration of all cards.

This marks all cards as incomplete, so the next generator run will
regenerate them with any new features (like etymology).

Usage:
    python scripts/clear_manifest_for_regen.py <output_dir> [--delete-cards]
    
Examples:
    # Just mark as incomplete (keeps existing files until regenerated):
    python scripts/clear_manifest_for_regen.py output/chinese/class/12-22-25/class/output
    
    # Mark incomplete AND delete existing cards:
    python scripts/clear_manifest_for_regen.py output/chinese/class/12-22-25/class/output --delete-cards
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.common.manifest import load_output_manifest, save_output_manifest


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/clear_manifest_for_regen.py <output_dir> [--delete-cards]")
        sys.exit(1)
    
    output_dir = Path(sys.argv[1])
    delete_cards = "--delete-cards" in sys.argv
    
    if not output_dir.exists():
        print(f"Error: Output directory does not exist: {output_dir}")
        sys.exit(1)
    
    # Load manifest
    manifest = load_output_manifest(output_dir)
    file_status = manifest.get("file_status", {})
    
    if not file_status:
        print(f"No words found in manifest for {output_dir}")
        sys.exit(0)
    
    # Mark all words as incomplete
    new_status = {word: False for word in file_status.keys()}
    save_output_manifest(output_dir, new_status)
    
    print(f"✓ Marked {len(new_status)} words as incomplete in {output_dir}")
    
    if delete_cards:
        deleted = 0
        for word in file_status.keys():
            md_file = output_dir / f"{word}.md"
            if md_file.exists():
                md_file.unlink()
                deleted += 1
        print(f"✓ Deleted {deleted} existing card files")
    
    print(f"\nRun the generator to regenerate cards:")
    print(f"  .venv/bin/python generate.py --config {output_dir.parent}/input/-config.json --verbose")


if __name__ == "__main__":
    main()

