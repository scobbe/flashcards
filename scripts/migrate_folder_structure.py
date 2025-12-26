#!/usr/bin/env python3
"""Migrate folder structure to input/generated layout.

For each folder with a -config.json:
1. Create input/ subfolder
2. Create generated/ subfolder  
3. Move -config.json and -input.raw.txt to input/
4. Move all other files to generated/
5. Update -config.json with output_dir: "../generated"
"""

import json
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
OUTPUT_ROOT = PROJECT_ROOT / "output"

CONFIG_FILENAME = "-config.json"
INPUT_FILES = {"-config.json", "-input.raw.txt"}


def migrate_folder(folder: Path, dry_run: bool = False) -> None:
    """Migrate a single folder to the new structure."""
    config_path = folder / CONFIG_FILENAME
    if not config_path.exists():
        return
    
    # Skip if already migrated (has input/ subfolder with config)
    input_dir = folder / "input"
    if (input_dir / CONFIG_FILENAME).exists():
        print(f"[skip] Already migrated: {folder}")
        return
    
    print(f"[migrate] {folder}")
    
    # Create directories
    input_dir = folder / "input"
    generated_dir = folder / "generated"
    
    if not dry_run:
        input_dir.mkdir(exist_ok=True)
        generated_dir.mkdir(exist_ok=True)
    
    # Collect files to move
    input_files = []
    generated_files = []
    
    for item in folder.iterdir():
        if item.name in ("input", "generated"):
            continue  # Skip the new directories
        
        if item.name in INPUT_FILES:
            input_files.append(item)
        else:
            generated_files.append(item)
    
    # Move input files
    for item in input_files:
        dest = input_dir / item.name
        print(f"  -> input/{item.name}")
        if not dry_run:
            shutil.move(str(item), str(dest))
    
    # Move generated files
    for item in generated_files:
        dest = generated_dir / item.name
        print(f"  -> generated/{item.name}")
        if not dry_run:
            if item.is_dir():
                shutil.move(str(item), str(dest))
            else:
                shutil.move(str(item), str(dest))
    
    # Update config with output_dir
    new_config_path = input_dir / CONFIG_FILENAME
    if not dry_run and new_config_path.exists():
        with open(new_config_path, encoding="utf-8") as f:
            config = json.load(f)
        
        config["output_dir"] = "../generated"
        
        with open(new_config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        
        print(f"  [updated] {CONFIG_FILENAME} with output_dir")


def find_folders_to_migrate(root: Path) -> list[Path]:
    """Find all folders with -config.json that need migration."""
    folders = []
    for config_path in root.rglob(CONFIG_FILENAME):
        folder = config_path.parent
        # Skip if this is already in an 'input' subfolder
        if folder.name == "input":
            continue
        folders.append(folder)
    return sorted(folders)


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Migrate folder structure")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done")
    args = parser.parse_args()
    
    folders = find_folders_to_migrate(OUTPUT_ROOT)
    print(f"Found {len(folders)} folders to migrate\n")
    
    for folder in folders:
        migrate_folder(folder, dry_run=args.dry_run)
        print()
    
    if args.dry_run:
        print("\n[dry-run] No changes made. Run without --dry-run to apply.")
    else:
        print("\n[done] Migration complete!")


if __name__ == "__main__":
    main()

