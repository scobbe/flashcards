"""Main processing logic for output generation."""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from lib.common.utils import is_cjk_char
from lib.common.logging import (
    log_debug,
    set_thread_log_context,
    DEFAULT_PARALLEL_WORKERS,
)
from lib.common.manifest import is_word_complete, mark_word_complete, init_output_manifest
from lib.output.html import (
    fetch_wiktionary_html_status,
    section_header,
    save_html_with_parsed,
    load_html_for_api,
)
from lib.output.etymology import (
    extract_back_fields_from_html,
    _etymology_complete,
    _collect_components_from_back,
    _parse_component_english_map,
    _parse_component_forms_map,
)
from lib.output.cards import (
    read_parsed_input,
    write_simple_card_md,
    render_grammar_folder,
)
from lib.output.components import (
    _generate_component_subtree,
    _get_cached_back_for_char,
)


def _process_single_row_written(
    folder: Path,
    idx: int,
    simp: str,
    trad: str,
    pin: str,
    eng: str,
    phrase: str,
    rel: str,
    model: Optional[str],
    verbose: bool,
    debug: bool,
    delay_s: float,
    comp_cache: Dict[str, object],
) -> Tuple[int, int]:
    """Process a single row in written mode (with etymology and Wiktionary).
    
    Uses manifest-based tracking: word is complete or not.
    For written mode, a word is only marked complete after ALL recursive decomposition is done.
    
    Returns (words_processed, cards_created) tuple.
    """
    headword = simp or trad
    file_base = f"{idx}.{headword}"
    out_dir = folder
    md_path = out_dir / f"{file_base}.md"
    successes_local = 0
    
    # Set log context for this thread
    set_thread_log_context(str(folder), file_base)
    
    # Skip if marked complete in manifest AND file exists
    if is_word_complete(out_dir, file_base) and md_path.exists():
        if verbose:
            print(f"[written] [skip] ✅ Already complete: {file_base}")
        return 1, 0
    
    # Not complete - delete existing files for this word (head + all children)
    for old_file in out_dir.glob(f"{file_base}.*"):
        old_file.unlink()
        if verbose:
            print(f"[written] [delete] Removing incomplete: {old_file.name}")

    # FULL ETYMOLOGY MODE: Build combined HTML fresh
    combined_sections: List[str] = []
    fetched_set: Dict[str, bool] = {}
    for form in [simp, trad]:
        form = (form or "").strip()
        if not form or form in fetched_set:
            continue
        fetched_set[form] = True
        form_html, form_status = fetch_wiktionary_html_status(form)
        if verbose:
            print(f"[written] [info] Wiktionary GET {form} -> {form_status}")
        if form_status == 200 and form_html:
            combined_sections.append(section_header(form) + form_html)
        else:
            combined_sections.append(section_header(form))
        if delay_s > 0:
            time.sleep(delay_s)
    combined_html_raw = "\n\n".join(combined_sections)
    
    html_path = out_dir / f"{file_base}.input.html"
    save_html_with_parsed(html_path, combined_html_raw, verbose=verbose)
    combined_html = load_html_for_api(html_path)
    
    if verbose:
        log_debug(debug, f"combined html size for {file_base}: {len(combined_html)}")
    log_debug(debug, f"calling extract_back_fields_from_html for {headword}; pinyin='{pin}'; HTML bytes={len(combined_html)}")
    back = extract_back_fields_from_html(
        simplified=simp or trad,
        traditional=trad or simp,
        english=eng,
        html=combined_html,
        model=model,
        verbose=verbose,
        parent_word=None,
        phrase=phrase,
    )
    if not _etymology_complete(back):
        if verbose:
            print(f"[written] [warn] Incomplete etymology for {file_base}; retrying once")
        back = extract_back_fields_from_html(
            simplified=simp or trad,
            traditional=trad or simp,
            english=eng,
            html=combined_html,
            model=model,
            verbose=verbose,
            parent_word=None,
            phrase=phrase,
        )
    if verbose:
        et = back.get("etymology") if isinstance(back, dict) else None
        et_type = et.get("type") if isinstance(et, dict) else ""
        et_sr = et.get("simplification_rule") if isinstance(et, dict) else ""
        sr_flag = "present" if (simp and trad and simp != trad and et_sr) else "skipped"
        print(f"[written] [ok] Back fields extracted: etymology.type='{et_type}', simplification={sr_flag}")
    log_debug(debug, f"back keys for {headword}: {list(back.keys()) if isinstance(back, dict) else type(back)}")
    write_simple_card_md(
        out_dir,
        file_base,
        eng,
        trad or headword,
        simp or headword,
        pin,
        rel,
        back_fields=back,
    )
    log_debug(debug, f"wrote md for {file_base}: pinyin='{pin}', relation='{rel}'")
    
    # Recursive component decomposition for single characters
    try:
        if isinstance(back, dict) and isinstance(headword, str) and len(headword) == 1:
            comp_list = _collect_components_from_back(back)
            log_debug(debug, f"components for {headword}: {comp_list}")
            if comp_list:
                desc = (
                    back.get("etymology", {}).get("description")
                    if isinstance(back.get("etymology"), dict)
                    else ""
                )
                english_map = _parse_component_english_map(str(desc))
                forms_map = _parse_component_forms_map(str(desc))
                visited: set = set([headword])
                for ch in comp_list:
                    log_debug(debug, f"recurse into {file_base}.{ch} english='{english_map.get(ch, '')}'")
                    sub_simp, sub_trad = forms_map.get(ch, (ch, ch))
                    cached_global = _get_cached_back_for_char(ch)
                    if isinstance(cached_global, dict):
                        comp_cache[ch] = cached_global
                    _generate_component_subtree(
                        out_dir=out_dir,
                        prefix=file_base,
                        ch=ch,
                        component_english=english_map.get(ch, ""),
                        parent_english=eng,
                        model=model,
                        verbose=verbose,
                        debug=debug,
                        delay_s=delay_s,
                        visited=visited,
                        depth=1,
                        comp_cache=comp_cache,
                        simp_form=sub_simp,
                        trad_form=sub_trad,
                    )
    except Exception as e:
        if verbose:
            print(f"[written] [warn] sub-component generation failed for {file_base}: {e}")
        raise
    
    # Mark word as complete AFTER all recursive decomposition is done
    mark_word_complete(out_dir, file_base)
    successes_local += 1
    
    if verbose:
        print(f"[written] [ok] Card for {file_base}")
    return 1, successes_local


def process_folder_written(
    folder: Path,
    model: Optional[str],
    verbose: bool,
    debug: bool,
    delay_s: float,
) -> Tuple[int, int]:
    """Process a folder in written mode (with etymology and Wiktionary).
    
    Uses manifest-based tracking: each word is complete or not.
    For oral mode, use lib.output.oral.process_oral_folder instead.
    
    Returns (total_words, cards_created) tuple.
    """
    parsed_path = folder / "-input.parsed.csv"
    if not parsed_path.exists():
        if verbose:
            print(f"[written] [skip] No -input.parsed.csv in {folder}")
        return 0, 0
    rows = read_parsed_input(parsed_path)
    if verbose:
        print(f"[written] [info] Processing {len(rows)} vocabulary words from {folder.name}/")
    log_debug(debug, f"parsed rows sample: {rows[:3]}")
    out_dir = folder
    
    # Initialize output manifest with all expected words (all set to false initially)
    word_keys = [f"{idx}.{simp or trad}" for idx, (simp, trad, _, _, _, _) in enumerate(rows, start=1)]
    init_output_manifest(out_dir, word_keys)
    
    successes = 0
    comp_cache: Dict[str, object] = {}

    workers = DEFAULT_PARALLEL_WORKERS

    if workers == 1:
        for idx, (simp, trad, pin, eng, phrase, rel) in enumerate(rows, start=1):
            try:
                _, inc = _process_single_row_written(
                    folder, idx, simp, trad, pin, eng, phrase, rel,
                    model, verbose, debug, delay_s, comp_cache
                )
                successes += inc
            except KeyboardInterrupt:
                if verbose:
                    print("[written] [cancelled] Interrupted by user")
                return successes, len(rows)
            except Exception as e:
                if verbose:
                    print(f"[written] [error] Failed to build card for {(simp or trad)}: {e}")
                raise
    else:
        if verbose:
            print(f"[written] [info] Parallel workers: {workers}")
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = []
            for idx, (simp, trad, pin, eng, phrase, rel) in enumerate(rows, start=1):
                futures.append(
                    executor.submit(
                        _process_single_row_written,
                        folder, idx, simp, trad, pin, eng, phrase, rel,
                        model, verbose, debug, delay_s, comp_cache,
                    )
                )
            try:
                for fut in as_completed(futures):
                    words_inc, cards_inc = fut.result()
                    successes += cards_inc
            except KeyboardInterrupt:
                if verbose:
                    print("[written] [cancelled] Interrupted by user")
            except Exception as e:
                if verbose:
                    print(f"[written] [error] Worker failed: {e}")
                raise
    
    # Concatenate all .md files into -output.md
    _write_combined_output(out_dir, verbose)
    return len(rows), successes


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
                    print(f"[written] [warn] failed reading {p.name} for -output.md")
        content = "\n\n".join(parts) + ("\n" if parts else "")
        output_md.write_text(content, encoding="utf-8")
        if verbose:
            print(f"[written] [ok] Wrote {output_md.name} ({len(content)} bytes) with {len(md_files)} files")
    except Exception as e:
        if verbose:
            print(f"[written] [warn] failed to write -output.md: {e}")



