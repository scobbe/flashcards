"""Chinese flashcard processing - row and folder operations."""

import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List, Optional, Tuple

from lib.schema.base import CARD_DIVIDER
from lib.common import (
    set_thread_log_context, DEFAULT_PARALLEL_WORKERS,
    is_word_complete, mark_word_complete, mark_word_in_progress, mark_word_error, init_output_manifest,
)

from lib.output.chinese.wiktionary import fetch_wiktionary_etymology
from lib.output.chinese.cards import read_parsed_input, generate_card_content, write_card_md, save_to_cache


def process_chinese_row(
    folder: Path,
    idx: int,
    simp: str,
    trad: str,
    pin: str,
    eng: str,
    phrase: str,
    rel: str,
    model: Optional[str] = None,
    verbose: bool = False,
) -> Tuple[int, int]:
    """Process a single Chinese vocabulary word.

    Returns (words_processed, cards_created) tuple.
    """
    headword = simp or trad
    file_base = f"{idx}.{headword}"
    out_dir = folder
    md_path = out_dir / f"{file_base}.md"

    set_thread_log_context(str(folder), file_base)

    # Skip if already complete
    if is_word_complete(out_dir, file_base) and md_path.exists():
        if verbose:
            print(f"[chinese] [skip] Already complete: {file_base}")
        return 1, 0

    # Mark as in progress
    mark_word_in_progress(out_dir, file_base)

    # Delete existing file if incomplete
    if md_path.exists():
        md_path.unlink()
        if verbose:
            print(f"[chinese] [delete] Removing incomplete: {md_path.name}")

    if verbose:
        print(f"[chinese] [info] Generating card: {file_base}")

    try:
        # Fetch Wiktionary etymology for this word
        wiki_ety = fetch_wiktionary_etymology(simp or headword, trad or headword, verbose=verbose)

        # Generate all content in single API call
        input_examples = phrase if phrase and phrase.strip() and phrase.strip().lower() != "none" else None
        etymology, trad_api, components, characters, examples, in_contemporary, from_cache = generate_card_content(
            simp, trad, pin, eng, input_examples=input_examples,
            wiktionary_etymology=wiki_ety, model=model, verbose=verbose
        )
        trad = trad_api

        # Write complete cache entry for main headword only if newly generated
        if not from_cache:
            parts_to_cache = components if components else characters
            save_to_cache(
                simp or headword, simp or headword, trad, pin, eng,
                etymology=etymology, parts=parts_to_cache,
                examples=examples, in_contemporary_usage=in_contemporary, verbose=verbose,
            )

        # Write card
        md_path, subcomponent_errors = write_card_md(
            out_dir,
            file_base,
            simp or headword,
            trad or headword,
            pin,
            eng,
            characters=characters,
            components=components,
            etymology=etymology,
            examples=examples,
            model=model,
            verbose=verbose,
        )

        # Check for any errors
        if subcomponent_errors:
            error_msg = f"Subcomponent errors: {'; '.join(subcomponent_errors)}"
            mark_word_error(out_dir, file_base, error_msg)
            if verbose:
                print(f"[chinese] [ERROR] Card has subcomponent errors: {file_base}")
                for err in subcomponent_errors:
                    print(f"  - {err}")
            return 1, 1

        mark_word_complete(out_dir, file_base)

        if verbose:
            print(f"[chinese] [ok] Card created: {file_base}")
        return 1, 1

    except Exception as e:
        mark_word_error(out_dir, file_base, str(e))
        if verbose:
            print(f"[chinese] [error] Failed to generate card for {file_base}: {e}")
        raise


def _clear_output_folder(out_dir: Path, verbose: bool = False) -> None:
    """Clear all contents from output folder."""
    if not out_dir.exists():
        return

    for item in out_dir.iterdir():
        if item.is_file():
            item.unlink()
            if verbose:
                print(f"[chinese] [clear] Removed: {item.name}")
        elif item.is_dir():
            shutil.rmtree(item)
            if verbose:
                print(f"[chinese] [clear] Removed directory: {item.name}")


def _get_input_parsed_dir(out_dir: Path) -> Path:
    """Get the input-parsed directory (sibling to output folder)."""
    input_parsed_dir = out_dir.parent / "input-parsed"
    input_parsed_dir.mkdir(parents=True, exist_ok=True)
    return input_parsed_dir


def _write_combined_output(out_dir: Path, verbose: bool = False) -> None:
    """Concatenate all .md files into -output.md."""
    try:
        output_name = "-output.md"
        output_md = out_dir / output_name

        md_files = [p for p in sorted(out_dir.glob("*.md")) if not p.name.startswith("-output") and not p.name.startswith("-")]
        parts: List[str] = []
        for p in md_files:
            try:
                parts.append(p.read_text(encoding="utf-8", errors="ignore").rstrip())
            except Exception:
                if verbose:
                    print(f"[chinese] [warn] failed reading {p.name} for {output_name}")
        content = f"\n{CARD_DIVIDER}\n".join(parts) + ("\n" if parts else "")
        output_md.write_text(content, encoding="utf-8")
        if verbose:
            print(f"[chinese] [ok] Wrote {output_name} ({len(content)} bytes) with {len(md_files)} files")
    except Exception as e:
        if verbose:
            print(f"[chinese] [warn] failed to write output: {e}")


def process_chinese_folder(
    folder: Path,
    model: Optional[str] = None,
    verbose: bool = False,
    workers: Optional[int] = None,
) -> Tuple[int, int]:
    """Process a folder of Chinese vocabulary words.

    Args:
        folder: Output folder for generated cards
        model: OpenAI model name
        verbose: Enable verbose logging
        workers: Number of parallel workers (default: DEFAULT_PARALLEL_WORKERS)

    Returns (total_words, cards_created) tuple.
    """
    out_dir = folder

    # Get input-parsed directory
    input_parsed_dir = _get_input_parsed_dir(out_dir)

    # Clear output folder
    _clear_output_folder(out_dir, verbose=verbose)

    # Read input from input-parsed directory
    parsed_path = input_parsed_dir / "-input.parsed.csv"
    if not parsed_path.exists():
        if verbose:
            print(f"[chinese] [skip] No parsed input at {parsed_path}")
        return 0, 0

    rows = read_parsed_input(parsed_path)
    # Skip sub-words (relation field not empty)
    all_rows = [(idx, s, t, p, e, ph, r) for idx, (s, t, p, e, ph, r) in enumerate(rows, start=1) if not r.strip()]

    if not all_rows:
        if verbose:
            print(f"[chinese] [skip] No parsed input in {input_parsed_dir}")
        return 0, 0

    # Initialize manifest
    word_keys = [f"{idx}.{simp or trad}" for idx, simp, trad, _, _, _, _ in all_rows]
    init_output_manifest(out_dir, word_keys)

    rows_to_process = all_rows

    if verbose:
        print(f"[chinese] [info] Processing {len(rows_to_process)} vocabulary words from {folder.name}/")

    total_cards = 0
    num_workers = workers if workers is not None else DEFAULT_PARALLEL_WORKERS

    if num_workers == 1:
        for idx, simp, trad, pin, eng, phrase, rel in rows_to_process:
            try:
                _, inc = process_chinese_row(
                    folder, idx, simp, trad, pin, eng, phrase, rel, model, verbose
                )
                total_cards += inc
            except Exception as e:
                if verbose:
                    print(f"[chinese] [error] Failed to build card for {(simp or trad)}: {e}")
                raise
    else:
        if verbose:
            print(f"[chinese] [info] Parallel workers: {num_workers}")
        with ThreadPoolExecutor(max_workers=num_workers) as executor:
            futures = []
            for idx, simp, trad, pin, eng, phrase, rel in rows_to_process:
                futures.append(
                    executor.submit(
                        process_chinese_row,
                        folder, idx, simp, trad, pin, eng, phrase, rel, model, verbose
                    )
                )
            for fut in as_completed(futures):
                try:
                    _, cards_inc = fut.result()
                    total_cards += cards_inc
                except Exception as e:
                    if verbose:
                        print(f"[chinese] [error] Worker failed: {e}")
                    raise

    # Write combined output
    _write_combined_output(out_dir, verbose)

    return len(rows_to_process), total_cards
