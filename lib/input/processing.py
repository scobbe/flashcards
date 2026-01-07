"""Main input processing logic."""

import re
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from lib.common.utils import is_cjk_char
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


def _show_progress(stop_event: threading.Event, prefix: str) -> None:
    """Show progress message while waiting."""
    print(f"{prefix} - Waiting for API response....")
    while not stop_event.is_set():
        time.sleep(0.1)




# Manifest-based tracking (simplified)
from lib.common.manifest import (
    is_chunk_complete, mark_chunk_complete, init_input_manifest
)


def _process_raw_input(
    raw_path: Path, model: str | None, verbose: bool, folder: str,
    output_dir: Optional[Path] = None,
    skip_subwords: bool = False,
) -> Tuple[Path, List[Tuple[str, str, str, str, str]], Dict[str, Tuple[str, str, str, str]], Dict[str, List[str]]]:
    """Process a raw input file and return parsed data.

    Uses manifest-based tracking to skip already-processed files.
    """
    # Use output_dir if provided, otherwise use raw_path.parent
    out_dir = output_dir if output_dir else raw_path.parent

    # Output is always -input.parsed.csv
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
    
    text = raw_path.read_text(encoding="utf-8", errors="ignore")

    # Single OpenAI call to extract everything
    if verbose:
        stop_event = threading.Event()
        progress_thread = threading.Thread(
            target=_show_progress,
            args=(stop_event, f"[./{folder}] [api] 🤖 Parsing vocab from {raw_path.name}")
        )
        progress_thread.start()

    try:
        quintuples = call_openai_for_vocab_and_forms(text, model=model)
    except Exception as e:
        if verbose:
            stop_event.set()
            progress_thread.join()
        # Re-raise - don't cache failures
        raise RuntimeError(f"OpenAI parsing failed for {raw_path.name}: {e}") from e

    if verbose:
        stop_event.set()
        progress_thread.join()
        print(f"[./{folder}] [ok] ✅ Parsed {len(quintuples)} entries from {raw_path.name}")

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
                    print(f"[./{folder}] [ok] ✅ Got {total_subs} subwords for {raw_path.name}")
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

    # Initialize manifest
    init_input_manifest(out_dir, [final_key])

    # Process the file
    out_path, quintuples, _, _ = _process_raw_input(
        raw_path, model, verbose, folder, out_dir, skip_subwords
    )

    if verbose:
        print(f"[./{folder}] [done] ✅ Processed {len(quintuples)} vocab words")

    return out_path, quintuples


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

