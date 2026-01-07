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

Usage:
    python generate.py --config output/general/1000/input/-config.json --verbose
"""

import argparse
import os
import sys
from pathlib import Path
from typing import List, Optional, Tuple

from lib.common.utils import _load_env_file


def parse_chunk_range(chunk_arg: Optional[str]) -> Optional[Tuple[int, int]]:
    """Parse a chunk range argument like '1-5' or '3'.
    
    Returns (start, end) tuple (1-indexed, inclusive) or None if no range specified.
    """
    if not chunk_arg:
        return None
    
    chunk_arg = chunk_arg.strip()
    if "-" in chunk_arg:
        parts = chunk_arg.split("-")
        if len(parts) == 2:
            try:
                start = int(parts[0])
                end = int(parts[1])
                if start < 1:
                    start = 1
                if end < start:
                    end = start
                return (start, end)
            except ValueError:
                pass
    else:
        try:
            n = int(chunk_arg)
            return (n, n)
        except ValueError:
            pass
    
    return None
from lib.common.config import load_folder_config, get_output_dir, CONFIG_FILENAME, clear_output_dir_for_no_cache
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
    chunk_range: Optional[Tuple[int, int]] = None,
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
    
    # Resolve paths
    raw_path = input_folder / config.raw_input_file
    output_dir = get_output_dir(input_folder, config)

    # Clear output dir if cache is disabled (do this BEFORE checking manifest)
    if not config.cache:
        cleared = clear_output_dir_for_no_cache(input_folder, config)
        if verbose and cleared > 0:
            print(f"[cache] Cleared {cleared} items from generated folder")

    # Check input manifest to see if parsing is already complete
    input_manifest = load_input_manifest(output_dir)
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
        print(f"📝 Output type: {config.output_type}")
    
    # Step 1: Parse raw input if needed
    # Skip parsing if manifest shows all chunks are complete
    needs_parsing = raw_path.exists() and not parsing_complete
    if needs_parsing:
        if verbose:
            if chunk_range:
                print(f"[input] Parsing {raw_path.name} (chunks {chunk_range[0]}-{chunk_range[1]})...")
            else:
                print(f"[input] Parsing {raw_path.name}...")
        try:
            if config.output_type == "english":
                # Simple English parsing (no OpenAI needed for input)
                process_english_input(raw_path, output_dir, verbose=verbose)
            else:
                # Chinese vocab parsing with OpenAI
                # Always skip subword extraction (unified chinese mode)
                process_input_file(raw_path, model=model, verbose=verbose, output_dir=output_dir, skip_subwords=True, chunk_range=chunk_range)
        except Exception as e:
            print(f"[error] Input parsing failed: {e}", file=sys.stderr)
            return 0, 0

        # Re-check manifest after parsing
        input_manifest = load_input_manifest(output_dir)
        parsing_complete = (
            input_manifest.get("complete", 0) > 0 and
            input_manifest.get("pending", 0) == 0 and
            input_manifest.get("in_progress", 0) == 0 and
            input_manifest.get("error", 0) == 0
        )

    # Input must be 100% complete before proceeding to output
    if not parsing_complete:
        input_manifest = load_input_manifest(output_dir)
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
        return process_chinese_folder(output_dir, model=model, verbose=verbose, chunk_range=chunk_range, workers=workers)


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
        "--chunks",
        type=str,
        default=None,
        help="Chunk range to process, e.g. '1-5' or '3'. Only processes input parsing for these chunks.",
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
    
    # Parse chunk range if provided
    chunk_range = parse_chunk_range(args.chunks)
    
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
        chunk_range=chunk_range,
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
