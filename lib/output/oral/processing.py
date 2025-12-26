"""Oral mode processing logic.

Oral mode is simpler than written mode:
- No Wiktionary fetching
- No etymology extraction
- No component decomposition
- Uses OpenAI only for example sentences
- Writes simple cards: Chinese front, pinyin+definition+example on back
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from lib.common.logging import set_thread_log_context, DEFAULT_PARALLEL_WORKERS
from lib.common.manifest import is_word_complete, mark_word_complete, init_output_manifest
from lib.common.utils import is_cjk_char
from lib.output.oral.cards import write_oral_card_md, generate_example_sentences, generate_character_breakdown
from lib.output.cards import read_parsed_input


def process_oral_row(
    folder: Path,
    idx: int,
    simp: str,
    trad: str,
    pin: str,
    eng: str,
    phrase: str,
    rel: str,
    parent_lookup: Dict[str, Tuple[str, str, str]],
    model: Optional[str] = None,
    verbose: bool = False,
) -> Tuple[int, int]:
    """Process a single row in oral mode.
    
    Uses manifest-based tracking: word is complete or not.
    
    Returns (words_processed, cards_created) tuple.
    """
    headword = simp or trad
    file_base = f"{idx}.{headword}"
    out_dir = folder
    md_path = out_dir / f"{file_base}.md"
    
    # Set log context for this thread
    set_thread_log_context(str(folder), file_base)
    
    # Skip if marked complete in manifest AND file exists
    if is_word_complete(out_dir, file_base) and md_path.exists():
        if verbose:
            print(f"[oral] [skip] ✅ Already complete: {file_base}")
        return 1, 0
    
    # Not complete - delete existing file if any
    if md_path.exists():
        md_path.unlink()
        if verbose:
            print(f"[oral] [delete] Removing incomplete: {md_path.name}")
    
    if verbose:
        print(f"[oral] [info] Generating card: {file_base}")
    
    # Extract parent word info for sub-words
    parent_chinese = ""
    rel_stripped = rel.strip()
    if rel_stripped and parent_lookup:
        q1 = rel_stripped.find('"')
        q2 = rel_stripped.rfind('"')
        if q1 != -1 and q2 != -1 and q2 > q1:
            parent_english = rel_stripped[q1 + 1 : q2]
            parent_info = parent_lookup.get(parent_english)
            if parent_info:
                p_simp, p_trad, _ = parent_info
                if p_trad and p_trad != p_simp:
                    parent_chinese = f"{p_simp}({p_trad})"
                else:
                    parent_chinese = p_simp
    
    # Generate example sentences via OpenAI (one per meaning)
    # Pass phrase as input_examples context if available (skip "None" or empty)
    input_examples = phrase if phrase and phrase.strip() and phrase.strip().lower() != "none" else None
    examples = generate_example_sentences(simp, trad, pin, eng, input_examples=input_examples, model=model)
    if verbose and examples:
        context_note = " (with input context)" if input_examples else ""
        print(f"[oral] [api] Got {len(examples)} example(s) for {headword}{context_note}")
    
    # Generate character breakdown for multi-character words
    characters = None
    cjk_chars = [ch for ch in (simp or headword) if is_cjk_char(ch)]
    if len(cjk_chars) > 1:
        characters = generate_character_breakdown(simp, trad, model=model)
        if verbose and characters:
            print(f"[oral] [api] Got {len(characters)} character breakdown(s) for {headword}")
    
    # Write card
    write_oral_card_md(
        out_dir,
        file_base,
        simp or headword,
        trad or headword,
        pin,
        eng,
        rel,
        parent_chinese=parent_chinese,
        examples=examples,
        characters=characters,
        verbose=verbose,
    )
    
    # Mark word as complete in manifest
    mark_word_complete(out_dir, file_base)
    
    if verbose:
        print(f"[oral] [ok] Card created: {file_base}")
    return 1, 1


def _read_all_chunk_csvs(folder: Path) -> List[Tuple[int, int, str, str, str, str, str, str]]:
    """Read ALL parsed chunk CSVs and return rows with global indices and chunk numbers.
    
    Returns list of (global_idx, chunk_num, simp, trad, pin, eng, phrase, rel) tuples.
    """
    import re
    all_rows_with_idx: List[Tuple[int, int, str, str, str, str, str, str]] = []
    
    # Find all chunk CSVs
    chunk_files = sorted(folder.glob("-input.parsed.*.csv"))
    
    global_idx = 0
    for chunk_file in chunk_files:
        # Extract chunk number from filename like -input.parsed.001.csv
        match = re.match(r"-input\.parsed\.(\d+)\.csv", chunk_file.name)
        if not match:
            continue
        
        chunk_num = int(match.group(1))
        rows = read_parsed_input(chunk_file)
        for simp, trad, pin, eng, phrase, rel in rows:
            # Skip sub-words
            if rel.strip():
                continue
            global_idx += 1
            all_rows_with_idx.append((global_idx, chunk_num, simp, trad, pin, eng, phrase, rel))
    
    return all_rows_with_idx


def process_oral_folder(
    folder: Path,
    model: Optional[str] = None,
    verbose: bool = False,
    chunk_range: Optional[Tuple[int, int]] = None,
) -> Tuple[int, int]:
    """Process a folder in oral mode.
    
    Uses manifest-based tracking: each word is complete or not.
    Skips sub-word entries (no decomposition in oral mode).
    
    Args:
        folder: Output folder for generated cards
        model: OpenAI model name
        verbose: Enable verbose logging
        chunk_range: If specified, process only words from those chunks with correct global indices
    
    Returns (total_words, cards_created) tuple.
    """
    out_dir = folder
    
    # Read ALL chunk CSVs to get global word list and correct indices
    all_words_with_chunks = _read_all_chunk_csvs(folder)
    
    if not all_words_with_chunks:
        # Fall back to -input.parsed.csv if no chunk CSVs
        parsed_path = folder / "-input.parsed.csv"
        if not parsed_path.exists():
            if verbose:
                print(f"[oral] [skip] No parsed input in {folder}")
            return 0, 0
        
        all_rows = read_parsed_input(parsed_path)
        rows = [(s, t, p, e, ph, r) for s, t, p, e, ph, r in all_rows if not r.strip()]
        # chunk_num=0 for non-chunked files
        all_words_with_chunks = [(idx, 0, s, t, p, e, ph, r) for idx, (s, t, p, e, ph, r) in enumerate(rows, start=1)]
    
    # Initialize output manifest with ALL expected words from ALL chunks
    word_keys = [f"{idx}.{simp or trad}" for idx, chunk_num, simp, trad, _, _, _, _ in all_words_with_chunks]
    init_output_manifest(out_dir, word_keys)
    
    # Filter to only words in the current chunk range if specified
    if chunk_range:
        # Filter by actual chunk number, not assumed word ranges
        start_chunk, end_chunk = chunk_range
        rows_to_process = [(idx, s, t, p, e, ph, r) for idx, chunk_num, s, t, p, e, ph, r in all_words_with_chunks 
                          if start_chunk <= chunk_num <= end_chunk]
        if verbose and rows_to_process:
            first_idx = rows_to_process[0][0]
            last_idx = rows_to_process[-1][0]
            print(f"[oral] [info] Processing words {first_idx}-{last_idx} (chunks {start_chunk}-{end_chunk})")
    else:
        rows_to_process = [(idx, s, t, p, e, ph, r) for idx, chunk_num, s, t, p, e, ph, r in all_words_with_chunks]
    
    if verbose:
        print(f"[oral] [info] Processing {len(rows_to_process)} vocabulary words from {folder.name}/")
    
    total_cards = 0
    workers = DEFAULT_PARALLEL_WORKERS
    
    if workers == 1:
        for idx, simp, trad, pin, eng, phrase, rel in rows_to_process:
            try:
                _, inc = process_oral_row(
                    folder, idx, simp, trad, pin, eng, phrase, rel, {}, model, verbose
                )
                total_cards += inc
            except Exception as e:
                if verbose:
                    print(f"[oral] [error] Failed to build card for {(simp or trad)}: {e}")
                raise
    else:
        if verbose:
            print(f"[oral] [info] Parallel workers: {workers}")
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = []
            for idx, simp, trad, pin, eng, phrase, rel in rows_to_process:
                futures.append(
                    executor.submit(
                        process_oral_row,
                        folder, idx, simp, trad, pin, eng, phrase, rel, {}, model, verbose
                    )
                )
            for fut in as_completed(futures):
                try:
                    _, cards_inc = fut.result()
                    total_cards += cards_inc
                except Exception as e:
                    if verbose:
                        print(f"[oral] [error] Worker failed: {e}")
                    raise
    
    # Write combined output
    _write_combined_output(out_dir, verbose, chunk_range=chunk_range)
    
    return len(rows_to_process), total_cards


def _write_combined_output(out_dir: Path, verbose: bool = False, chunk_range: Optional[Tuple[int, int]] = None) -> None:
    """Concatenate all .md files into -output.md (or -output.XXX-YYY.md for partial chunks)."""
    try:
        # Name output file based on chunk range
        if chunk_range:
            output_name = f"-output.{chunk_range[0]:03d}-{chunk_range[1]:03d}.md"
        else:
            output_name = "-output.md"
        output_md = out_dir / output_name
        
        # Exclude all -output*.md files from collection
        md_files = [p for p in sorted(out_dir.glob("*.md")) if not p.name.startswith("-output")]
        parts: List[str] = []
        for p in md_files:
            try:
                parts.append(p.read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                if verbose:
                    print(f"[oral] [warn] failed reading {p.name} for {output_name}")
        content = "\n\n".join(parts) + ("\n" if parts else "")
        output_md.write_text(content, encoding="utf-8")
        if verbose:
            print(f"[oral] [ok] Wrote {output_name} ({len(content)} bytes) with {len(md_files)} files")
    except Exception as e:
        if verbose:
            print(f"[oral] [warn] failed to write output: {e}")

