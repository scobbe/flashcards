"""Component decomposition and subtree generation."""

import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from lib.common.utils import is_cjk_char
from lib.common.logging import log_debug, set_thread_log_context
from lib.output.html import (
    fetch_wiktionary_html_status,
    section_header,
    save_html_with_parsed,
    load_html_for_api,
    sanitize_html,
)
from lib.output.etymology import (
    extract_back_fields_from_html,
    _etymology_complete,
    _collect_components_from_back,
    _parse_component_english_map,
    _parse_component_forms_map,
    _map_radical_variant_to_primary,
)
from lib.output.cards import write_simple_card_md


# Global shared component back-fields cache across threads
_GLOBAL_COMPONENT_CACHE: Dict[str, object] = {}
_GLOBAL_COMPONENT_CACHE_LOCK = threading.Lock()


def _get_cached_back_for_char(ch: str) -> Optional[object]:
    """Get cached back fields for a character."""
    if not isinstance(ch, str) or not ch:
        return None
    with _GLOBAL_COMPONENT_CACHE_LOCK:
        return _GLOBAL_COMPONENT_CACHE.get(ch)


def _set_cached_back_for_char(ch: str, back: object) -> None:
    """Set cached back fields for a character."""
    if not isinstance(ch, str) or not ch:
        return
    if not isinstance(back, dict):
        return
    with _GLOBAL_COMPONENT_CACHE_LOCK:
        _GLOBAL_COMPONENT_CACHE[ch] = back


def _read_md(out_dir: Path, base: str) -> str:
    """Read markdown file content."""
    p = out_dir / f"{base}.md"
    try:
        return p.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def _extract_description_line(md_text: str) -> str:
    """Extract description line from markdown."""
    if not isinstance(md_text, str) or not md_text:
        return ""
    for line in md_text.splitlines():
        if "**description:**:" in line:
            try:
                return line.split("**description:**:", 1)[1].strip()
            except Exception:
                continue
    return ""


def _extract_english_heading(md_text: str) -> str:
    """Extract English heading from markdown."""
    if not isinstance(md_text, str) or not md_text:
        return ""
    for line in md_text.splitlines():
        line = line.strip()
        if line.startswith("## "):
            return line[3:].strip()
    return ""


def _generate_component_subtree(
    out_dir: Path,
    prefix: str,
    ch: str,
    component_english: str,
    parent_english: str,
    model: Optional[str],
    verbose: bool,
    debug: bool,
    delay_s: float,
    visited: set,
    depth: int,
    max_depth: int = 5,
    comp_cache: Optional[Dict[str, object]] = None,
    simp_form: Optional[str] = None,
    trad_form: Optional[str] = None,
) -> None:
    """Recursively generate component subtree cards."""
    if depth > max_depth:
        return
    target_ch = _map_radical_variant_to_primary(ch)
    if target_ch in visited:
        return
    visited.add(target_ch)

    simplified_form = simp_form or target_ch
    traditional_form = trad_form or simplified_form

    word_id = f"{prefix}.{target_ch}"
    md_path = out_dir / f"{word_id}.md"
    
    # Update log context
    set_thread_log_context(str(out_dir), word_id)
    
    # Skip if file already exists (component files are regenerated at top level)
    if md_path.exists():
        if verbose:
            print(f"[skip] Component exists: {md_path.name}")
        return
    
    # Prepare HTML for this component
    html_path = out_dir / f"{word_id}.input.html"
    if html_path.exists():
        combined_html = load_html_for_api(html_path)
        if verbose:
            print(f"[info] Using cached HTML for {word_id}")
    else:
        combined_sections: List[str] = []
        fetched_set: Dict[str, bool] = {}
        for form in [simplified_form, traditional_form]:
            form = (form or "").strip()
            if not form or form in fetched_set:
                continue
            fetched_set[form] = True
            form_html, form_status = fetch_wiktionary_html_status(form)
            if verbose:
                print(f"[fetch] Wiktionary: {form} → HTTP {form_status}")
            if form_status == 200 and form_html:
                combined_sections.append(section_header(form) + form_html)
            else:
                combined_sections.append(section_header(form))
            if delay_s > 0:
                time.sleep(delay_s)
        combined_html_raw = "\n\n".join(combined_sections)
        save_html_with_parsed(html_path, combined_html_raw, verbose=verbose)
        combined_html = load_html_for_api(html_path)

    # Generate back fields for this component
    back: Dict[str, object] | object
    cached_global = _get_cached_back_for_char(target_ch)
    if isinstance(cached_global, dict):
        log_debug(debug, f"global cache hit for component '{target_ch}'")
        back = cached_global
    elif comp_cache is not None and target_ch in comp_cache:
        log_debug(debug, f"local cache hit for component '{target_ch}'")
        back = comp_cache[target_ch]
    else:
        back = extract_back_fields_from_html(
            simplified=simplified_form,
            traditional=traditional_form,
            english=component_english,
            html=combined_html,
            model=model,
            verbose=verbose,
            parent_word=parent_english,
        )
        if not _etymology_complete(back):
            if verbose:
                print(f"[warn] Incomplete etymology for {word_id}; retrying once")
            back = extract_back_fields_from_html(
                simplified=simplified_form,
                traditional=traditional_form,
                english=component_english,
                html=combined_html,
                model=model,
                verbose=verbose,
                parent_word=parent_english,
            )
        if isinstance(back, dict):
            _set_cached_back_for_char(target_ch, back)
            if comp_cache is not None:
                comp_cache[target_ch] = back
    
    # Get pinyin from back fields
    pin = ""
    if isinstance(back, dict):
        pv = back.get("pronunciation")
        if isinstance(pv, str) and pv.strip():
            pin = pv.strip()

    # Write the component markdown
    write_simple_card_md(
        out_dir,
        word_id,
        component_english,
        traditional_form,
        simplified_form,
        pin,
        f'sub-component of "{parent_english}"',
        back_fields=back,
    )
    if verbose:
        print(f"[ok] Component card for {word_id}")

    # Recurse into this component's own components
    comps = _collect_components_from_back(back if isinstance(back, dict) else {})
    if not comps:
        return
    desc = (
        back.get("etymology", {}).get("description")
        if isinstance(back, dict) and isinstance(back.get("etymology"), dict)
        else ""
    )
    english_map = _parse_component_english_map(str(desc))
    forms_map = _parse_component_forms_map(str(desc))
    for sub_ch in comps:
        mapped_sub = _map_radical_variant_to_primary(sub_ch)
        if mapped_sub == target_ch:
            continue
        sub_eng = english_map.get(mapped_sub, "")
        sub_simp, sub_trad = forms_map.get(mapped_sub, (mapped_sub, mapped_sub))
        _generate_component_subtree(
            out_dir,
            prefix=word_id,
            ch=mapped_sub,
            component_english=sub_eng,
            parent_english=component_english,
            model=model,
            verbose=verbose,
            debug=debug,
            delay_s=delay_s,
            visited=visited,
            depth=depth + 1,
            max_depth=max_depth,
            comp_cache=comp_cache,
            simp_form=sub_simp,
            trad_form=sub_trad,
        )


def regenerate_single_file(
    out_dir: Path,
    file_base: str,
    target_name: str,
    simp: str,
    trad: str,
    eng: str,
    model: Optional[str],
    verbose: bool,
    debug: bool,
    delay_s: float,
) -> None:
    """Regenerate a single file that failed validation."""
    if target_name in (f"{file_base}.md",):
        # Rebuild the headword card
        combined_sections: List[str] = []
        fetched_set: Dict[str, bool] = {}
        for form in [simp, trad]:
            form = (form or "").strip()
            if not form or form in fetched_set:
                continue
            fetched_set[form] = True
            form_html, form_status = fetch_wiktionary_html_status(form)
            if verbose:
                print(f"[fetch] Wiktionary: {form} → HTTP {form_status}")
            if form_status == 200 and form_html:
                combined_sections.append(section_header(form) + form_html)
            else:
                combined_sections.append(section_header(form))
            if delay_s > 0:
                time.sleep(delay_s)
        combined_html_raw = "\n\n".join(combined_sections)
        combined_html = sanitize_html(combined_html_raw)
        back = extract_back_fields_from_html(
            simplified=simp or trad,
            traditional=trad or simp,
            english=eng,
            html=combined_html,
            model=model,
            verbose=verbose,
            parent_word=None,
        )
        if not _etymology_complete(back):
            if verbose:
                print(f"[warn] Incomplete etymology for {file_base}; retrying once")
            back = extract_back_fields_from_html(
                simplified=simp or trad,
                traditional=trad or simp,
                english=eng,
                html=combined_html,
                model=model,
                verbose=verbose,
                parent_word=None,
            )
        write_simple_card_md(
            out_dir,
            file_base,
            eng,
            trad or (simp or trad),
            simp or (trad or simp),
            "",
            "",
            back_fields=back,
        )
        return
    
    # Regenerate specific sub-component card
    stem = target_name
    if stem.endswith(".md"):
        stem = stem[:-3]
    if not stem.startswith(file_base + "."):
        return
    chain = stem.split(".")
    if len(chain) < 2:
        return
    target_char = chain[-1]
    parent_prefix = ".".join(chain[:-1])
    parent_md = _read_md(out_dir, parent_prefix)
    parent_english = _extract_english_heading(parent_md)
    desc_line = _extract_description_line(parent_md)
    comp_eng_map = _parse_component_english_map(desc_line)
    comp_eng = comp_eng_map.get(target_char, "")
    init_visited = set(tok for tok in chain[:-1] if len(tok) == 1 and is_cjk_char(tok))
    _generate_component_subtree(
        out_dir=out_dir,
        prefix=parent_prefix,
        ch=target_char,
        component_english=comp_eng,
        parent_english=parent_english or eng,
        model=model,
        verbose=verbose,
        debug=debug,
        delay_s=delay_s,
        visited=init_visited,
        depth=1,
        comp_cache={},
    )

