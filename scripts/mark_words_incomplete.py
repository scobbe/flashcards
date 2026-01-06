#!/usr/bin/env python3
"""Mark specific words as incomplete for regeneration.

Usage:
    python scripts/mark_words_incomplete.py <output_dir> <word1> [word2] [word3] ...
    
Example:
    python scripts/mark_words_incomplete.py output/chinese/class/12-22-25/class/output 1.度假 20.如果 24.买不起
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.common.manifest import mark_word_incomplete, load_output_manifest


def main():
    if len(sys.argv) < 3:
        print("Usage: python scripts/mark_words_incomplete.py <output_dir> <word1> [word2] ...")
        print("Example: python scripts/mark_words_incomplete.py output/chinese/class/12-22-25/class/output 1.度假")
        sys.exit(1)
    
    output_dir = Path(sys.argv[1])
    words = sys.argv[2:]
    
    if not output_dir.exists():
        print(f"Error: Output directory does not exist: {output_dir}")
        sys.exit(1)
    
    # Load manifest to verify words exist
    manifest = load_output_manifest(output_dir)
    file_status = manifest.get("file_status", {})
    
    for word in words:
        if word in file_status:
            mark_word_incomplete(output_dir, word)
            print(f"✓ Marked incomplete: {word}")
            
            # Delete existing .md file if present
            md_file = output_dir / f"{word}.md"
            if md_file.exists():
                md_file.unlink()
                print(f"  Deleted: {md_file.name}")
        else:
            print(f"✗ Word not found in manifest: {word}")
            print(f"  Available words: {list(file_status.keys())[:10]}...")


if __name__ == "__main__":
    main()

