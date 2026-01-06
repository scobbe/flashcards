#!/usr/bin/env python3
"""Regenerate all flashcard directories that have issues.

This script finds all directories marked for regeneration and runs
the generator on each one.

Usage:
    python scripts/regen_all.py [--dry-run] [--chinese-only] [--limit N]
    
    --dry-run: Show what would be regenerated without running
    --chinese-only: Only regenerate Chinese cards
    --limit N: Limit to first N directories
"""

import subprocess
import sys
from pathlib import Path
from typing import List, Tuple

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


def find_directories_needing_regen(project_root: Path, chinese_only: bool = False) -> List[Tuple[Path, int]]:
    """Find output directories that need regeneration.
    
    Returns list of (input_dir, word_count) tuples.
    """
    from lib.common.manifest import load_output_manifest
    
    output_root = project_root / "output"
    dirs_to_regen = []
    
    # Find all output directories
    for output_dir in output_root.rglob("output"):
        if not output_dir.is_dir():
            continue
        
        # Check if input dir exists with config
        input_dir = output_dir.parent / "input"
        config_path = input_dir / "-config.json"
        if not config_path.exists():
            continue
        
        # Skip English if chinese_only
        if chinese_only and "english" in str(output_dir):
            continue
        
        # Check manifest for incomplete words
        manifest = load_output_manifest(output_dir)
        file_status = manifest.get("file_status", {})
        
        if not file_status:
            continue
        
        incomplete = sum(1 for v in file_status.values() if not v)
        if incomplete > 0:
            dirs_to_regen.append((input_dir, incomplete))
    
    # Sort by number of incomplete (smallest first for faster feedback)
    return sorted(dirs_to_regen, key=lambda x: x[1])


def main():
    dry_run = "--dry-run" in sys.argv
    chinese_only = "--chinese-only" in sys.argv
    limit = None
    
    for i, arg in enumerate(sys.argv):
        if arg == "--limit" and i + 1 < len(sys.argv):
            try:
                limit = int(sys.argv[i + 1])
            except ValueError:
                pass
    
    project_root = Path(__file__).parent.parent
    
    print("Finding directories needing regeneration...")
    dirs = find_directories_needing_regen(project_root, chinese_only=chinese_only)
    
    if not dirs:
        print("✅ No directories need regeneration!")
        return
    
    if limit:
        dirs = dirs[:limit]
    
    total_words = sum(count for _, count in dirs)
    print(f"\nFound {len(dirs)} directories with {total_words} incomplete cards:")
    print("-" * 60)
    
    for input_dir, count in dirs:
        rel_path = input_dir.relative_to(project_root)
        print(f"  {rel_path}: {count} cards")
    
    if dry_run:
        print("\n[DRY RUN] Would regenerate the above directories.")
        return
    
    print(f"\n{'=' * 60}")
    print("STARTING REGENERATION")
    print("=" * 60)
    
    python_path = project_root / ".venv" / "bin" / "python"
    generate_script = project_root / "generate.py"
    
    for i, (input_dir, count) in enumerate(dirs, 1):
        config_path = input_dir / "-config.json"
        rel_path = input_dir.relative_to(project_root)
        
        print(f"\n[{i}/{len(dirs)}] Regenerating {rel_path} ({count} cards)...")
        
        try:
            result = subprocess.run(
                [str(python_path), str(generate_script), "--config", str(config_path), "--verbose"],
                cwd=str(project_root),
                capture_output=False,
                text=True,
            )
            
            if result.returncode == 0:
                print(f"✓ Completed {rel_path}")
            else:
                print(f"✗ Failed {rel_path} (exit code {result.returncode})")
        except Exception as e:
            print(f"✗ Error processing {rel_path}: {e}")
    
    print(f"\n{'=' * 60}")
    print("REGENERATION COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()

