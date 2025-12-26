"""Main input processing logic."""

import glob
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from lib.common.utils import is_cjk_char, line_has_cjk, _sha256_file
from lib.common.logging import DEFAULT_PARALLEL_WORKERS
from lib.input.vocab import (
    call_openai_for_vocab_and_forms,
    call_openai_forms_for_words,
)
from lib.input.subwords import (
    call_openai_subwords_for_words,
    format_with_subwords_csv,
)
from lib.input.grammar import (
    call_openai_for_grammar,
    write_parsed_grammar_csv,
)


# Maximum number of lines with CJK characters per chunk
MAX_CJK_LINES_PER_CHUNK = 50


def _show_progress(stop_event: threading.Event, prefix: str) -> None:
    """Show progress message while waiting."""
    print(f"{prefix} - Waiting for API response....")
    while not stop_event.is_set():
        time.sleep(0.1)


def split_raw_into_chunks(raw_path: Path, output_dir: Path, verbose: bool = False) -> List[Path]:
    """Split a raw input file into chunks with at most MAX_CJK_LINES_PER_CHUNK CJK lines each.
    
    Args:
        raw_path: Path to the raw input file
        output_dir: Directory to write chunk files to (generated files go here)
        
    Returns a list of chunk file paths. If the file is small enough, returns just the original.
    Chunk files are named: -input.raw.001.txt, -input.raw.002.txt, etc.
    """
    text = raw_path.read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines(keepends=True)
    
    # Count total CJK lines
    cjk_line_count = sum(1 for line in lines if line_has_cjk(line))
    
    # If small enough, no need to split
    if cjk_line_count <= MAX_CJK_LINES_PER_CHUNK:
        return [raw_path]
    
    # Split into chunks
    chunks: List[List[str]] = []
    current_chunk: List[str] = []
    current_cjk_count = 0
    
    for line in lines:
        has_cjk = line_has_cjk(line)
        
        # If adding this line would exceed the limit and we have content, start new chunk
        if has_cjk and current_cjk_count >= MAX_CJK_LINES_PER_CHUNK and current_chunk:
            chunks.append(current_chunk)
            current_chunk = []
            current_cjk_count = 0
        
        current_chunk.append(line)
        if has_cjk:
            current_cjk_count += 1
    
    # Don't forget the last chunk
    if current_chunk:
        chunks.append(current_chunk)
    
    # Write chunk files to output directory
    chunk_paths: List[Path] = []
    output_dir.mkdir(parents=True, exist_ok=True)
    
    for i, chunk_lines in enumerate(chunks, 1):
        chunk_filename = f"-input.raw.{i:03d}.txt"
        chunk_path = output_dir / chunk_filename
        chunk_path.write_text("".join(chunk_lines), encoding="utf-8")
        chunk_paths.append(chunk_path)
        if verbose:
            cjk_in_chunk = sum(1 for ln in chunk_lines if line_has_cjk(ln))
            print(f"  [chunk] Created {chunk_filename} ({cjk_in_chunk} CJK lines)")
    
    if verbose:
        print(f"  [split] Split {raw_path.name} into {len(chunks)} chunks ({cjk_line_count} total CJK lines)")
    
    return chunk_paths


def combine_parsed_csvs(chunk_parsed_paths: List[Path], final_path: Path, verbose: bool = False) -> None:
    """Combine multiple parsed CSV files into a single final CSV.
    
    Handles deduplication based on the first column (simplified character).
    """
    seen_words: Set[str] = set()
    all_lines: List[str] = []
    
    for parsed_path in chunk_parsed_paths:
        if not parsed_path.exists():
            continue
        text = parsed_path.read_text(encoding="utf-8", errors="ignore")
        for line in text.splitlines():
            if not line.strip():
                continue
            # Extract the first field (simplified) for deduplication
            parts = line.split(",", 1)
            word = parts[0].strip()
            if word and word not in seen_words:
                seen_words.add(word)
                all_lines.append(line)
    
    final_path.write_text("\n".join(all_lines) + "\n" if all_lines else "", encoding="utf-8")
    
    if verbose:
        print(f"  [combine] Combined {len(chunk_parsed_paths)} chunks -> {final_path.name} ({len(all_lines)} entries)")


def cleanup_chunk_files(parent: Path, verbose: bool = False) -> None:
    """Remove intermediate chunk files after combining."""
    # Clean up raw chunk files
    pattern = str(parent / "-input.raw.*.txt")
    for chunk_file in glob.glob(pattern):
        chunk_path = Path(chunk_file)
        # Match pattern -input.raw.NNN.txt where NNN is digits
        if re.match(r"-input\.raw\.\d{3}\.txt$", chunk_path.name):
            chunk_path.unlink()
            if verbose:
                print(f"  [cleanup] Removed {chunk_path.name}")
    
    # Clean up intermediate parsed files
    parsed_pattern = str(parent / "-input.parsed.*.csv")
    for parsed_file in glob.glob(parsed_pattern):
        parsed_path = Path(parsed_file)
        if re.match(r"-input\.parsed\.\d{3}\.csv$", parsed_path.name):
            parsed_path.unlink()
            if verbose:
                print(f"  [cleanup] Removed {parsed_path.name}")
    
    # Clean up parsed cache files
    cache_pattern = str(parent / "-input.parsed.*.cache.json")
    for cache_file in glob.glob(cache_pattern):
        cache_path = Path(cache_file)
        if re.match(r"-input\.parsed\.\d{3}\.cache\.json$", cache_path.name):
            cache_path.unlink()
            if verbose:
                print(f"  [cleanup] Removed {cache_path.name}")




# Manifest-based tracking (simplified)
from lib.common.manifest import (
    is_chunk_complete, mark_chunk_complete, init_input_manifest
)


def _process_chunk(
    chunk_path: Path, model: str | None, verbose: bool, folder: str,
    output_dir: Optional[Path] = None,
    skip_subwords: bool = False,
) -> Tuple[Path, List[Tuple[str, str, str, str, str]], Dict[str, Tuple[str, str, str, str]], Dict[str, List[str]]]:
    """Process a single chunk file and return parsed data.
    
    Uses manifest-based tracking: chunk is complete or not.
    No hashing - just checks if chunk is marked complete in manifest.
    """
    # Use output_dir if provided, otherwise use chunk_path.parent
    out_dir = output_dir if output_dir else chunk_path.parent
    
    # Determine output path and manifest key for this chunk
    if re.match(r"-input\.raw\.\d{3}\.txt$", chunk_path.name):
        chunk_num = chunk_path.name.replace("-input.raw.", "").replace(".txt", "")
        out_path = out_dir / f"-input.parsed.{chunk_num}.csv"
        manifest_key = f"-input.parsed.{chunk_num}.csv"
    else:
        out_path = out_dir / "-input.parsed.csv"
        manifest_key = "-input.parsed.csv"
    
    # Check manifest - skip if chunk is marked complete AND file exists
    if is_chunk_complete(out_dir, manifest_key) and out_path.exists():
        if verbose:
            print(f"[./{folder}] [skip] ✅ Already complete: {manifest_key}")
        # Read existing parsed file to return data
        try:
            lines = out_path.read_text(encoding="utf-8").splitlines()
            quintuples: List[Tuple[str, str, str, str, str]] = []
            for line in lines:
                if line.strip():
                    parts = line.split(",")
                    if len(parts) >= 5:
                        quintuples.append((parts[0], parts[1], parts[2], parts[3], parts[4] if len(parts) > 4 else ""))
            return out_path, quintuples, {}, {}
        except Exception:
            pass  # Fall through to reprocess
    
    text = chunk_path.read_text(encoding="utf-8", errors="ignore")
    
    # Single OpenAI call to extract everything
    if verbose:
        stop_event = threading.Event()
        progress_thread = threading.Thread(
            target=_show_progress,
            args=(stop_event, f"[./{folder}] [api] 🤖 Parsing vocab from {chunk_path.name}")
        )
        progress_thread.start()
    
    try:
        quintuples = call_openai_for_vocab_and_forms(text, model=model)
    except Exception as e:
        if verbose:
            stop_event.set()
            progress_thread.join()
        # Re-raise - don't cache failures
        raise RuntimeError(f"OpenAI parsing failed for {chunk_path.name}: {e}") from e
    
    if verbose:
        stop_event.set()
        progress_thread.join()
        print(f"[./{folder}] [ok] ✅ Parsed {len(quintuples)} entries from {chunk_path.name}")

    # Initialize subword structures
    sub_map: Dict[str, Tuple[str, str, str, str]] = {}
    parent_multi: Dict[str, List[str]] = {}
    
    # Skip subword extraction for oral mode
    if not skip_subwords:
        # Build subword set
        main_char_map: Dict[str, Tuple[str, str, str, str]] = {}
        for s, t, p, e, _ in quintuples:
            if len(s or t) == 1:
                main_char_map[s or t] = (s, t, p, e)
        subchars: List[str] = []
        seen_sub: Set[str] = set()
        for s, t, p, e, _ in quintuples:
            word = s or t
            if len(word) > 1:
                for ch in word:
                    if not is_cjk_char(ch) or ch in seen_sub or ch in main_char_map:
                        continue
                    seen_sub.add(ch)
                    subchars.append(ch)
        sub_map = dict(main_char_map)
        
        # Discover multi-character sub-words via OpenAI
        multi_inputs = [s or t for s, t, _, _, _ in quintuples if len((s or t)) > 1]
        if multi_inputs:
            try:
                if verbose:
                    stop_event = threading.Event()
                    progress_thread = threading.Thread(
                        target=_show_progress,
                        args=(stop_event, f"[./{folder}] [api] 🤖 Getting subwords for {len(multi_inputs)} multi-char words")
                    )
                    progress_thread.start()
                
                subwords_info = call_openai_subwords_for_words(multi_inputs, model=model)
                
                if verbose:
                    stop_event.set()
                    progress_thread.join()
                    total_subs = sum(len(v) for v in subwords_info.values())
                    print(f"[./{folder}] [ok] ✅ Got {total_subs} subwords for {chunk_path.name}")
            except Exception:
                if verbose:
                    stop_event.set()
                    progress_thread.join()
                subwords_info = {}
            for parent, subs in subwords_info.items():
                token_list: List[str] = []
                for ss, tt, pp, ee in subs:
                    key = ss or tt
                    if key and key not in sub_map:
                        sub_map[key] = (ss, tt, pp, ee)
                    if key:
                        token_list.append(key)
                if token_list:
                    parent_multi[parent] = token_list
        
        if subchars:
            try:
                if verbose:
                    stop_event = threading.Event()
                    progress_thread = threading.Thread(
                        target=_show_progress,
                        args=(stop_event, f"[./{folder}] [api] 🤖 Getting forms for {len(subchars)} component characters")
                    )
                    progress_thread.start()
                
                sub_triples = call_openai_forms_for_words(subchars, model=model)
                
                if verbose:
                    stop_event.set()
                    progress_thread.join()
                    print(f"[./{folder}] [ok] ✅ Got forms for {len(sub_triples)} components")
            except Exception:
                if verbose:
                    stop_event.set()
                    progress_thread.join()
                sub_triples = [(ch, ch, "", "") for ch in subchars]
            for s, t, p, e in sub_triples:
                key = s or t
                if key and key not in sub_map:
                    sub_map[key] = (s, t, p, e)

    # Write parsed CSV (out_path already set at top of function)
    out_path.write_text(
        format_with_subwords_csv(quintuples, sub_map, parent_multi, skip_subwords), encoding="utf-8"
    )
    
    # Mark chunk as complete in manifest (only if we got results)
    if quintuples:
        mark_chunk_complete(out_dir, manifest_key)
    
    if verbose:
        print(f"[./{folder}] [file] 💾 Created {out_path.name} ({len(quintuples)} items + subwords)")
    
    return out_path, quintuples, sub_map, parent_multi


def process_file(
    raw_path: Path, model: str | None, verbose: bool, *, 
    force_rebuild: bool = False, output_dir: Optional[Path] = None,
    skip_subwords: bool = False,
) -> Tuple[Path, List[Tuple[str, str, str, str, str]]]:
    """Process a raw input file and generate parsed CSV.
    
    This function now:
    1. Splits the raw file into chunks (max 50 CJK lines each)
    2. Processes each chunk separately
    3. Combines all chunk outputs into a single -input.parsed.csv
    4. Cleans up intermediate chunk files
    
    Args:
        raw_path: Path to the raw input file
        model: OpenAI model name
        verbose: Enable verbose logging
        force_rebuild: Force regeneration even if output exists
        output_dir: Directory for generated files. If None, uses raw_path.parent
        skip_subwords: If True, skip subword extraction (for oral mode)
    """
    # Compute relative path from project root
    project_root = Path(__file__).parent.parent.parent.resolve()
    try:
        folder = str(raw_path.parent.relative_to(project_root))
    except ValueError:
        folder = raw_path.parent.name
    
    # Use output_dir if provided, otherwise use raw_path.parent
    out_dir = output_dir if output_dir else raw_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    final_out_path = out_dir / "-input.parsed.csv"
    final_key = "-input.parsed.csv"
    
    # Check manifest - if final is marked complete AND file exists, skip
    if is_chunk_complete(out_dir, final_key) and final_out_path.exists() and not force_rebuild:
        if verbose:
            print(f"[./{folder}] [skip] ✅ Already complete: {final_out_path.name}")
        try:
            lines = final_out_path.read_text(encoding="utf-8").splitlines()
            quintuples = [(ln, "", "", "", "") for ln in lines if ln.strip()]
        except Exception:
            quintuples = []
        return final_out_path, quintuples
    
    # Split into chunks
    if verbose:
        print(f"[./{folder}] [split] Analyzing {raw_path.name} for chunking...")
    
    chunk_paths = split_raw_into_chunks(raw_path, out_dir, verbose=verbose)
    
    # If only one chunk (small file), process directly
    if len(chunk_paths) == 1 and chunk_paths[0] == raw_path:
        # Initialize manifest with just the final file
        init_input_manifest(out_dir, [final_key])
        out_path, quintuples, _, _ = _process_chunk(raw_path, model, verbose, folder, out_dir, skip_subwords)
        # Mark final as complete
        mark_chunk_complete(out_dir, final_key)
        return out_path, quintuples
    
    # Initialize manifest with all expected chunks + final
    chunk_keys = [f"-input.parsed.{i:03d}.csv" for i in range(1, len(chunk_paths) + 1)]
    chunk_keys.append(final_key)
    init_input_manifest(out_dir, chunk_keys)
    
    # Process each chunk in parallel
    workers = DEFAULT_PARALLEL_WORKERS
    if verbose:
        print(f"[./{folder}] [process] Processing {len(chunk_paths)} chunks with {workers} workers...")
    
    all_quintuples: List[Tuple[str, str, str, str, str]] = []
    all_sub_map: Dict[str, Tuple[str, str, str, str]] = {}
    all_parent_multi: Dict[str, List[str]] = {}
    chunk_parsed_paths: List[Path] = []
    
    # Map chunk index to results to maintain order
    chunk_results: Dict[int, Tuple[Path, List[Tuple[str, str, str, str, str]], Dict, Dict]] = {}
    
    if workers == 1:
        # Sequential processing
        for i, chunk_path in enumerate(chunk_paths, 1):
            if verbose:
                print(f"[./{folder}] [chunk {i}/{len(chunk_paths)}] Processing {chunk_path.name}...")
            
            parsed_path, quintuples, sub_map, parent_multi = _process_chunk(
                chunk_path, model, verbose, folder, None, skip_subwords
            )
            chunk_results[i] = (parsed_path, quintuples, sub_map, parent_multi)
    else:
        # Parallel processing
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {}
            for i, chunk_path in enumerate(chunk_paths, 1):
                future = executor.submit(_process_chunk, chunk_path, model, verbose, folder, out_dir, skip_subwords)
                futures[future] = (i, chunk_path)
            
            try:
                for future in as_completed(futures):
                    i, chunk_path = futures[future]
                    try:
                        parsed_path, quintuples, sub_map, parent_multi = future.result()
                        chunk_results[i] = (parsed_path, quintuples, sub_map, parent_multi)
                        if verbose:
                            print(f"[./{folder}] [chunk {i}/{len(chunk_paths)}] ✅ Done: {chunk_path.name}")
                    except Exception as e:
                        if verbose:
                            print(f"[./{folder}] [chunk {i}] ❌ Failed: {e}")
                        raise
            except KeyboardInterrupt:
                if verbose:
                    print(f"[./{folder}] [cancelled] Interrupted by user")
                raise
    
    # Collect results in order
    for i in sorted(chunk_results.keys()):
        parsed_path, quintuples, sub_map, parent_multi = chunk_results[i]
        chunk_parsed_paths.append(parsed_path)
        all_quintuples.extend(quintuples)
        all_sub_map.update(sub_map)
        all_parent_multi.update(parent_multi)
    
    # Combine all chunk parsed CSVs into the final one
    combine_parsed_csvs(chunk_parsed_paths, final_out_path, verbose=verbose)
    
    # Mark final as complete in manifest
    mark_chunk_complete(out_dir, "-input.parsed.csv")
    
    if verbose:
        print(f"[./{folder}] [done] ✅ Processed {len(all_quintuples)} total vocab words")
    
    return final_out_path, all_quintuples


def _process_single_raw_file(raw_path: Path, model: str | None, verbose: bool) -> int:
    """Process a single raw input file and return the number of items."""
    project_root = Path(__file__).parent.parent.parent.resolve()
    try:
        folder = str(raw_path.parent.relative_to(project_root))
    except ValueError:
        folder = raw_path.parent.name
    out_dir = raw_path.parent
    parsed_path = out_dir / "-input.parsed.csv"
    
    # Check manifest - if complete AND file exists, skip
    if is_chunk_complete(out_dir, "-input.parsed.csv") and parsed_path.exists():
        if verbose:
            print(f"[./{folder}] [skip] ✅ Already complete: {raw_path.name}")
        try:
            with parsed_path.open("r", encoding="utf-8") as f:
                items = [ln for ln in f.read().splitlines() if ln.strip()]
        except Exception:
            items = []
        return len(items)
    
    # Process
    if verbose:
        print(f"[./{folder}] [process] Processing {raw_path.name}...")
    _, items = process_file(raw_path, model=model, verbose=verbose, force_rebuild=True)
    if verbose:
        print(f"[./{folder}] [done] ✅ Processed {len(items)} vocab words")
    return len(items)


def _process_single_grammar_file(gpath: Path, model: str | None, verbose: bool) -> None:
    """Process a single grammar file."""
    project_root = Path(__file__).parent.parent.parent.resolve()
    try:
        folder = str(gpath.parent.relative_to(project_root))
    except ValueError:
        folder = gpath.parent.name
    out_dir = gpath.parent
    parsed_path = out_dir / "-input.parsed.grammar.csv"
    
    # Check manifest - if grammar is complete AND file exists, skip
    if is_chunk_complete(out_dir, "grammar") and parsed_path.exists():
        if verbose:
            print(f"[./{folder}] [skip] ✅ Grammar already complete")
        return
    
    # Process
    if verbose:
        print(f"[./{folder}] [api] 🤖 Extracting grammar rules from {gpath.name}")
    text = gpath.read_text(encoding="utf-8", errors="ignore")
    try:
        rules = call_openai_for_grammar(text, model=model)
    except Exception:
        rules = []
    write_parsed_grammar_csv(gpath, rules, verbose=verbose)
    mark_chunk_complete(out_dir, "grammar")
    if verbose:
        print(f"[./{folder}] [done] ✅ Grammar processed")

