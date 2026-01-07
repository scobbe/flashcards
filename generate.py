#!/usr/bin/env python3
"""Full flashcard generation pipeline.

This is the main entry point that runs both:
1. Input parsing: -input.raw.txt → -input.parsed.csv
2. Output generation: -input.parsed.csv → .md flashcards

Folder structure:
    output/general/1000/
        input/
            -config.json      (with output_dir: "../output")
            -input.raw.txt
        output/
            -input.parsed.csv
            1.word.md
            ...

If chunk_size is set in config, creates chunk subfolders instead:
    output/general/1000/
        input/
            -config.json      (with chunk_size: 50)
            -input.raw.txt
        chunks/
            chunk-001/
                input/-config.json
                input/-input.raw.txt
            chunk-002/
                ...

Usage:
    python generate.py --config output/general/1000/input/-config.json --verbose
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import List, Optional

from lib.common.utils import _load_env_file, is_cjk_char
from lib.common.config import load_folder_config, get_output_dir, CONFIG_FILENAME, clear_output_dir_for_no_cache


def create_chunk_folders(input_folder: Path, config, verbose: bool = False) -> int:
    """Split raw input into chunk subfolders based on chunk_size config.

    Creates chunks/ directory with chunk-001/, chunk-002/, etc.
    Each chunk folder has input/-config.json and input/-input.raw.txt.

    Returns number of chunks created.
    """
    raw_path = input_folder / config.raw_input_file
    if not raw_path.exists():
        print(f"[error] Raw input file not found: {raw_path}", file=sys.stderr)
        return 0

    # Read raw input and split by CJK lines
    with open(raw_path, encoding="utf-8") as f:
        lines = f.readlines()

    # Filter to lines containing CJK characters
    cjk_lines = [line for line in lines if any(is_cjk_char(c) for c in line)]

    if not cjk_lines:
        print(f"[error] No CJK lines found in {raw_path}", file=sys.stderr)
        return 0

    chunk_size = config.chunk_size
    chunks_dir = input_folder.parent / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)

    # Split into chunks
    num_chunks = (len(cjk_lines) + chunk_size - 1) // chunk_size

    for i in range(num_chunks):
        chunk_num = i + 1
        chunk_name = f"chunk-{chunk_num:03d}"
        chunk_dir = chunks_dir / chunk_name
        chunk_input_dir = chunk_dir / "input"
        chunk_input_dir.mkdir(parents=True, exist_ok=True)

        # Get lines for this chunk
        start_idx = i * chunk_size
        end_idx = min((i + 1) * chunk_size, len(cjk_lines))
        chunk_lines = cjk_lines[start_idx:end_idx]

        # Write chunk raw input
        chunk_raw_path = chunk_input_dir / "-input.raw.txt"
        with open(chunk_raw_path, "w", encoding="utf-8") as f:
            f.writelines(chunk_lines)

        # Write chunk config (without chunk_size)
        chunk_config = {
            "output_type": config.output_type,
            "raw_input_file": "-input.raw.txt",
            "output_dir": "../output",
        }
        chunk_config_path = chunk_input_dir / CONFIG_FILENAME
        with open(chunk_config_path, "w", encoding="utf-8") as f:
            json.dump(chunk_config, f, indent=2)

        if verbose:
            print(f"[chunk] Created {chunk_name} ({len(chunk_lines)} items)")

    return num_chunks
from lib.common.manifest import load_input_manifest
from lib.input import process_file as process_input_file
from lib.input.english import process_english_input
from lib.output.chinese import process_chinese_folder
from lib.output.english import process_english_folder


# Load .env on import
_load_env_file()




def process_folder(
    input_folder: Path,
    model: Optional[str],
    verbose: bool,
    debug: bool,
    delay_s: float,
    workers: Optional[int] = None,
) -> tuple[int, int]:
    """Process a folder: parse input then generate output.

    Args:
        input_folder: Path to the input/ folder containing -config.json and -input.raw.txt

    Returns (words_processed, cards_generated).
    """
    # Load config
    config = load_folder_config(input_folder)
    if not config:
        if verbose:
            print(f"[skip] No {CONFIG_FILENAME} found in {input_folder}")
        return 0, 0

    # If chunk_size is set, create chunk folders and exit
    if config.chunk_size:
        chunks_dir = input_folder.parent / "chunks"
        if chunks_dir.exists() and any(chunks_dir.iterdir()):
            if verbose:
                num_existing = len(list(chunks_dir.glob("chunk-*")))
                print(f"[skip] Chunk folders already exist ({num_existing} chunks in {chunks_dir})")
                print(f"[info] Run generator on individual chunk configs, e.g.:")
                print(f"       python generate.py --config {chunks_dir}/chunk-001/input/-config.json")
            return 0, 0

        if verbose:
            print(f"[chunk] Splitting input into chunks of {config.chunk_size}...")
        num_chunks = create_chunk_folders(input_folder, config, verbose=verbose)
        if verbose:
            print(f"[done] Created {num_chunks} chunk folders in {chunks_dir}")
            print(f"[info] Run generator on individual chunk configs, e.g.:")
            print(f"       python generate.py --config {chunks_dir}/chunk-001/input/-config.json")
        return 0, 0

    # Resolve paths
    raw_path = input_folder / config.raw_input_file
    output_dir = get_output_dir(input_folder, config)

    # Input-parsed directory is sibling to output directory
    input_parsed_dir = output_dir.parent / "input-parsed"
    input_parsed_dir.mkdir(parents=True, exist_ok=True)

    # Clear output dir if cache is disabled (do this BEFORE checking manifest)
    if not config.cache:
        cleared = clear_output_dir_for_no_cache(input_folder, config)
        if verbose and cleared > 0:
            print(f"[cache] Cleared {cleared} items from generated folder")

    # Check input manifest to see if parsing is already complete
    input_manifest = load_input_manifest(input_parsed_dir)
    parsing_complete = (
        input_manifest.get("complete", 0) > 0 and
        input_manifest.get("pending", 0) == 0 and
        input_manifest.get("in_progress", 0) == 0 and
        input_manifest.get("error", 0) == 0
    )

    # Ensure output dir exists
    output_dir.mkdir(parents=True, exist_ok=True)

    if verbose:
        print(f"📂 Input folder: {input_folder}")
        print(f"📁 Output folder: {output_dir}")
        print(f"📁 Input-parsed folder: {input_parsed_dir}")
        print(f"📝 Output type: {config.output_type}")

    # Step 1: Parse raw input if needed
    # Skip parsing if manifest shows all chunks are complete
    needs_parsing = raw_path.exists() and not parsing_complete
    if needs_parsing:
        if verbose:
            print(f"[input] Parsing {raw_path.name}...")
        try:
            if config.output_type == "english":
                # Simple English parsing (no OpenAI needed for input)
                process_english_input(raw_path, input_parsed_dir, verbose=verbose)
            else:
                # Chinese vocab parsing with OpenAI
                process_input_file(raw_path, model=model, verbose=verbose, output_dir=input_parsed_dir, skip_subwords=True)
        except Exception as e:
            print(f"[error] Input parsing failed: {e}", file=sys.stderr)
            return 0, 0

        # Re-check manifest after parsing
        input_manifest = load_input_manifest(input_parsed_dir)
        parsing_complete = (
            input_manifest.get("complete", 0) > 0 and
            input_manifest.get("pending", 0) == 0 and
            input_manifest.get("in_progress", 0) == 0 and
            input_manifest.get("error", 0) == 0
        )

    # Input must be 100% complete before proceeding to output
    if not parsing_complete:
        input_manifest = load_input_manifest(input_parsed_dir)
        if verbose:
            complete = input_manifest.get("complete", 0)
            pending = input_manifest.get("pending", 0)
            in_progress = input_manifest.get("in_progress", 0)
            error = input_manifest.get("error", 0)
            print(f"[skip] Input not complete: {complete} complete, {pending} pending, {in_progress} in_progress, {error} error")
        return 0, 0

    # Step 2: Generate output (all modes read from -input.parsed.csv)
    if config.output_type == "english":
        return process_english_folder(output_dir, model=model, verbose=verbose, workers=workers)
    else:
        # Chinese mode (always recursive)
        return process_chinese_folder(output_dir, model=model, verbose=verbose, workers=workers)


def main(argv: Optional[List[str]] = None) -> int:
    """Main entry point for the full pipeline."""
    parser = argparse.ArgumentParser(
        description="Full flashcard generation: parse -input.raw.txt and generate .md cards"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--config",
        type=str,
        help="Path to -config.json file",
    )
    group.add_argument(
        "--dry-run",
        type=str,
        nargs="?",
        const="all",
        help="Run dry-run tests. Options: 'all' (default), 'english', 'chinese'",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("OPENAI_MODEL"),
        help="OpenAI model name (overrides OPENAI_MODEL)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.0,
        help="Delay between Wiktionary requests (default: 0)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Number of parallel workers (default: uses DEFAULT_PARALLEL_WORKERS)",
    )
    args = parser.parse_args(argv)
    
    # Handle --dry-run flag
    if args.dry_run:
        project_root = Path(__file__).parent.resolve()

        # Map dry-run options to config paths
        all_configs = {
            "english": project_root / "output/english/dry-run/input" / CONFIG_FILENAME,
            "chinese": project_root / "output/chinese/dry-run/input" / CONFIG_FILENAME,
        }

        # Determine which configs to run
        if args.dry_run == "all":
            dry_run_configs = list(all_configs.values())
        elif args.dry_run in all_configs:
            dry_run_configs = [all_configs[args.dry_run]]
        else:
            print(f"[error] Invalid dry-run option: {args.dry_run}. Use: all, english, chinese", file=sys.stderr)
            return 2

        total_words = 0
        total_cards = 0

        for config_path in dry_run_configs:
            if not config_path.exists():
                print(f"[warn] Dry-run config not found: {config_path}", file=sys.stderr)
                continue
            
            input_folder = config_path.parent
            
            if args.verbose:
                print(f"\n{'=' * 60}")
                print(f"🚀 Dry-Run: {input_folder.parent.name}/{input_folder.name}")
                print(f"{'=' * 60}")
            
            words, cards = process_folder(
                input_folder,
                model=args.model,
                verbose=args.verbose,
                debug=args.debug,
                delay_s=args.delay,
                workers=args.workers,
            )
            total_words += words
            total_cards += cards
            
            if args.verbose:
                print(f"   Words: {words}, Cards: {cards}")
        
        if args.verbose:
            print(f"\n{'=' * 60}")
            print("✅ Dry-Run Complete!")
            print(f"   Total words processed: {total_words}")
            print(f"   Total cards generated: {total_cards}")
            print(f"{'=' * 60}\n")
        
        return 0
    
    # Handle --config flag
    config_path = Path(args.config)
    if not config_path.exists():
        print(f"[error] Config file does not exist: {config_path}", file=sys.stderr)
        return 2
    
    if config_path.name != CONFIG_FILENAME:
        print(f"[error] Config file must be named {CONFIG_FILENAME}, got: {config_path.name}", file=sys.stderr)
        return 2
    
    # Input folder is the parent of the config file
    input_folder = config_path.parent

    if args.verbose:
        print(f"\n{'=' * 60}")
        print("🚀 Full Pipeline: Input Parsing + Card Generation")
        print(f"{'=' * 60}")
    
    words, cards = process_folder(
        input_folder,
        model=args.model,
        verbose=args.verbose,
        debug=args.debug,
        delay_s=args.delay,
        workers=args.workers,
    )
    
    if args.verbose:
        print(f"\n{'=' * 60}")
        print("✅ Complete!")
        print(f"   Words processed: {words}")
        print(f"   Cards generated: {cards}")
        print(f"{'=' * 60}\n")
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
