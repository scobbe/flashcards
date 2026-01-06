"""English mode processing logic.

English mode is simple:
- No Wiktionary fetching
- No etymology extraction (in the Chinese sense)
- Uses OpenAI to generate definition, origin, and pronunciation
- Writes simple cards: word on front, content on back
"""

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List, Optional, Tuple

from lib.common.logging import set_thread_log_context, DEFAULT_PARALLEL_WORKERS
from lib.common.manifest import is_word_complete, mark_word_complete, init_output_manifest
from lib.output.english.cards import write_english_card_md, generate_english_card_content


def _sanitize_filename(name: str) -> str:
    """Sanitize a string for use as a filename."""
    return re.sub(r'[/\\:*?"<>|]', '_', name)


def read_english_input(parsed_path: Path) -> List[str]:
    """Read English vocabulary words from input file.
    
    Supports two formats:
    1. Simple text: one word per line
    2. CSV: word in first column
    
    Lines starting with # are treated as comments.
    """
    words: List[str] = []
    
    text = parsed_path.read_text(encoding="utf-8")
    
    for line in text.splitlines():
        line = line.strip()
        
        # Skip empty lines and comments
        if not line or line.startswith("#"):
            continue
        
        # Handle CSV format (take first column)
        if "," in line:
            word = line.split(",")[0].strip()
        else:
            word = line
        
        # Clean up the word
        word = word.strip().strip('"').strip("'").strip()
        
        if word:
            words.append(word)
    
    return words


def process_english_row(
    folder: Path,
    idx: int,
    word: str,
    model: Optional[str] = None,
    verbose: bool = False,
) -> Tuple[int, int]:
    """Process a single English vocabulary word.
    
    Uses manifest-based tracking: word is complete or not.
    
    Returns (words_processed, cards_created) tuple.
    """
    file_base = f"{idx}.{word}"
    safe_file_base = _sanitize_filename(file_base)
    out_dir = folder
    md_path = out_dir / f"{safe_file_base}.md"
    
    # Set log context for this thread
    set_thread_log_context(str(folder), file_base)
    
    # Skip if marked complete in manifest AND file exists
    if is_word_complete(out_dir, file_base) and md_path.exists():
        if verbose:
            print(f"[english] [skip] ✅ Already complete: {file_base}")
        return 1, 0
    
    # Not complete - delete existing file if any
    if md_path.exists():
        md_path.unlink()
        if verbose:
            print(f"[english] [delete] Removing incomplete: {md_path.name}")
    
    if verbose:
        print(f"[english] [info] Generating card: {file_base}")
    
    # Generate content via OpenAI
    content = generate_english_card_content(word, model=model)
    
    if verbose:
        def_count = len(content.get("definition", []))
        etym_count = len(content.get("etymology", []))
        hist_count = len(content.get("history", []))
        pron = "yes" if content.get("pronunciation") else "no"
        print(f"[english] [api] Generated for {word}: {def_count} defs, {etym_count} etyms, {hist_count} hist, pron={pron}")
    
    # Write card (pass both file_base for filename and word for display)
    write_english_card_md(out_dir, file_base, word, content, verbose=verbose)
    
    # Mark word as complete in manifest
    mark_word_complete(out_dir, file_base)
    
    if verbose:
        print(f"[english] [ok] Card created: {file_base}")
    
    return 1, 1


def process_english_folder(
    folder: Path,
    model: Optional[str] = None,
    verbose: bool = False,
) -> Tuple[int, int]:
    """Process a folder in English mode.
    
    Reads from -input.parsed.csv (created by input parsing step).
    Uses manifest-based tracking: each word is complete or not.
    
    Args:
        folder: Output folder for generated cards (contains -input.parsed.csv)
        model: OpenAI model name
        verbose: Enable verbose logging
    
    Returns (total_words, cards_created) tuple.
    """
    parsed_path = folder / "-input.parsed.csv"
    if not parsed_path.exists():
        if verbose:
            print(f"[english] [skip] No -input.parsed.csv in {folder}")
        return 0, 0
    
    words = read_english_input(parsed_path)
    
    if verbose:
        print(f"[english] [info] Read {len(words)} words from {parsed_path.name}")
    
    if verbose:
        print(f"[english] [info] Processing {len(words)} English words from {folder.name}/")
    
    out_dir = folder
    
    # Initialize output manifest with all expected words
    word_keys = [f"{idx}.{word}" for idx, word in enumerate(words, start=1)]
    init_output_manifest(out_dir, word_keys)
    
    total_cards = 0
    workers = DEFAULT_PARALLEL_WORKERS
    
    if workers == 1:
        for idx, word in enumerate(words, start=1):
            try:
                _, inc = process_english_row(folder, idx, word, model, verbose)
                total_cards += inc
            except Exception as e:
                if verbose:
                    print(f"[english] [error] Failed to build card for {word}: {e}")
                raise
    else:
        if verbose:
            print(f"[english] [info] Parallel workers: {workers}")
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = []
            for idx, word in enumerate(words, start=1):
                futures.append(
                    executor.submit(process_english_row, folder, idx, word, model, verbose)
                )
            for fut in as_completed(futures):
                try:
                    _, cards_inc = fut.result()
                    total_cards += cards_inc
                except Exception as e:
                    if verbose:
                        print(f"[english] [error] Worker failed: {e}")
                    raise
    
    # Write combined output
    _write_combined_output(out_dir, verbose)
    
    return len(words), total_cards


def _write_combined_output(out_dir: Path, verbose: bool = False) -> None:
    """Concatenate all .md files into -output.md."""
    try:
        output_md = out_dir / "-output.md"
        md_files = [p for p in sorted(out_dir.glob("*.md")) if p.name != "-output.md"]
        parts: List[str] = []
        for p in md_files:
            try:
                parts.append(p.read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                if verbose:
                    print(f"[english] [warn] failed reading {p.name} for -output.md")
        content = "\n\n".join(parts) + ("\n" if parts else "")
        output_md.write_text(content, encoding="utf-8")
        if verbose:
            print(f"[english] [ok] Wrote {output_md.name} ({len(content)} bytes) with {len(md_files)} files")
    except Exception as e:
        if verbose:
            print(f"[english] [warn] failed to write -output.md: {e}")

