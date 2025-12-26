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
from typing import List, Optional

from lib.common.utils import _load_env_file
from lib.common.config import load_folder_config, get_output_dir, CONFIG_FILENAME, clear_output_dir_for_no_cache
from lib.input import process_file as process_input_file
from lib.input.english import process_english_input
from lib.output import process_folder_written
from lib.output.oral import process_oral_folder
from lib.output.english import process_english_folder


# Load .env on import
_load_env_file()




def process_folder(
    input_folder: Path,
    model: Optional[str],
    verbose: bool,
    debug: bool,
    delay_s: float,
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
    parsed_path = output_dir / "-input.parsed.csv"
    
    # Clear output dir if cache is disabled
    if not config.cache:
        cleared = clear_output_dir_for_no_cache(input_folder, config)
        if verbose and cleared > 0:
            print(f"[cache] Cleared {cleared} items from generated folder")
    
    # Ensure output dir exists
    output_dir.mkdir(parents=True, exist_ok=True)
    
    if verbose:
        print(f"📂 Input folder: {input_folder}")
        print(f"📁 Output folder: {output_dir}")
        print(f"📝 Output type: {config.output_type}")
    
    # Step 1: Parse raw input if needed
    if raw_path.exists() and not parsed_path.exists():
        if verbose:
            print(f"[input] Parsing {raw_path.name}...")
        try:
            if config.output_type == "english":
                # Simple English parsing (no OpenAI needed for input)
                process_english_input(raw_path, output_dir, verbose=verbose)
            else:
                # Chinese vocab parsing with OpenAI
                # Skip subword extraction for oral mode
                skip_subwords = config.output_type == "oral"
                process_input_file(raw_path, model=model, verbose=verbose, output_dir=output_dir, skip_subwords=skip_subwords)
        except Exception as e:
            print(f"[error] Input parsing failed: {e}", file=sys.stderr)
            return 0, 0
    
    if not parsed_path.exists():
        if verbose:
            print(f"[skip] No -input.parsed.csv found in {output_dir}")
        return 0, 0
    
    # Step 2: Generate output (all modes read from -input.parsed.csv)
    if config.output_type == "oral":
        return process_oral_folder(output_dir, model=model, verbose=verbose)
    elif config.output_type == "english":
        return process_english_folder(output_dir, model=model, verbose=verbose)
    else:
        return process_folder_written(output_dir, model, verbose, debug, delay_s)


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
        action="store_true",
        help="Run both oral and written dry-run configs",
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
    args = parser.parse_args(argv)
    
    # Handle --dry-run flag
    if args.dry_run:
        project_root = Path(__file__).parent.resolve()
        dry_run_configs = [
            project_root / "output/dry-run/oral/input" / CONFIG_FILENAME,
            project_root / "output/dry-run/written/input" / CONFIG_FILENAME,
        ]
        
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
