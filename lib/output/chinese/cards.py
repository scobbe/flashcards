"""Chinese flashcard content generation and markdown writing."""

import csv
import time
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from lib.schema.base import FRONT_BACK_DIVIDER
from lib.schema.chinese import (
    generate_system_prompt_no_examples,
    generate_examples_system_prompt,
    format_field_for_display,
    extract_to_cache_format,
    extract_from_cache,
    is_cache_valid,
    CHINESE_DISPLAY_SCHEMA,
)
from lib.common import OpenAIClient, add_subcomponent_error, is_cjk_char

from lib.output.chinese.cache import read_cache, write_cache
from lib.output.chinese.wiktionary import fetch_wiktionary_etymology


def read_parsed_input(parsed_path: Path) -> List[Tuple[str, str, str, str, str, str]]:
    """Read parsed input CSV file."""
    rows: List[Tuple[str, str, str, str, str, str]] = []
    if not parsed_path.exists():
        return rows
    with parsed_path.open("r", encoding="utf-8") as f:
        reader = csv.reader(f)
        for rec in reader:
            if not rec:
                continue
            simp = rec[0].strip() if len(rec) > 0 else ""
            trad = rec[1].strip() if len(rec) > 1 else simp
            pin = rec[2].strip() if len(rec) > 2 else ""
            eng = rec[3].strip() if len(rec) > 3 else ""
            phrase = rec[4].strip() if len(rec) > 4 else ""
            rel = rec[5].strip() if len(rec) > 5 else ""
            if simp:
                rows.append((simp, trad, pin, eng, phrase, rel))
    return rows


def _parts_to_tuples(parts: List[dict]) -> List[Tuple[str, str, str, str]]:
    """Convert parts list of dicts to list of tuples."""
    result = []
    for part in parts:
        if isinstance(part, dict):
            ch = str(part.get("char", "")).strip()
            trad = str(part.get("trad", ch)).strip()
            pin = str(part.get("pinyin", "")).strip()
            eng = str(part.get("english", "")).strip()
            if ch:
                result.append((ch, trad or ch, pin, eng))
    return result


def _normalize_examples(examples: List[dict]) -> List[dict]:
    """Normalize examples list of dicts."""
    result = []
    for ex in examples:
        if isinstance(ex, dict):
            ch = str(ex.get("chinese", "")).strip()
            pin = str(ex.get("pinyin", "")).strip()
            eng = str(ex.get("english", "")).strip()
            if ch:
                result.append({"chinese": ch, "pinyin": pin, "english": eng})
    return result


def _tuples_to_parts(parts: List[Tuple[str, str, str, str]]) -> List[dict]:
    """Convert parts tuples back to dicts for cache storage."""
    return [{"char": c, "trad": t, "pinyin": p, "english": e} for c, t, p, e in parts]




def save_to_cache(
    word: str,
    simplified: str,
    traditional: str,
    pinyin: str,
    english: str,
    etymology: Optional[Dict[str, str]],
    parts: Optional[List[Tuple[str, str, str, str]]],
    examples: Optional[List[dict]],
    in_contemporary_usage: bool,
    verbose: bool,
) -> None:
    """Save card data to cache with validation.

    Validates that we have valid data before caching.
    """
    # Don't cache if there was an error
    if etymology and etymology.get("error"):
        print(f"[chinese] [cache] Not caching {word} - API error: {etymology.get('error')}")
        return

    # Don't cache without examples (unless archaic character)
    if not examples and in_contemporary_usage:
        print(f"[chinese] [cache] Not caching {word} - no examples")
        return

    cache_data = {
        "simplified": simplified,
        "traditional": traditional,
        "pinyin": pinyin,
        "english": english,
        "etymology": etymology or {},
        "parts": _tuples_to_parts(parts) if parts else [],
        "in_contemporary_usage": in_contemporary_usage,
        "examples": examples,
    }
    write_cache(word, cache_data, verbose=verbose)


def generate_card_content(
    simplified: str,
    traditional: str,
    pinyin: str,
    english: str,
    input_examples: Optional[str] = None,
    wiktionary_etymology: Optional[str] = None,
    model: Optional[str] = None,
    verbose: bool = False,
) -> Tuple[Dict[str, str], str, List[Tuple[str, str, str, str]], List[Tuple[str, str, str, str]], List[dict], bool, bool]:
    """Generate all card content in a single API call.

    Returns (etymology_dict, traditional, components, character_breakdown, examples, in_contemporary_usage, from_cache).
    """
    word = simplified or traditional
    cjk_chars = [ch for ch in simplified if is_cjk_char(ch)]
    is_single = len(cjk_chars) == 1

    # Check cache first
    cached = read_cache(word, verbose=verbose)
    if is_cache_valid(cached):
        # Extract from cache using schema helper
        extracted = extract_from_cache(cached)
        parts = _parts_to_tuples(extracted["parts"])
        examples = _normalize_examples(extracted["examples"])

        if is_single:
            components = parts
            char_breakdown = []
        else:
            components = []
            char_breakdown = parts

        return (
            extracted["etymology"],
            extracted["traditional"],
            components,
            char_breakdown,
            examples,
            extracted["in_contemporary_usage"],
            True,  # from_cache
        )

    # Generate system prompt from schema
    variant = "single_char" if is_single else "multi_char"

    # Build user prompt for etymology
    if is_single:
        user = f"Character: {simplified}"
        user += f"\nPinyin: {pinyin}\nMeaning: {english}"
        if wiktionary_etymology:
            user += f"\n\n**MANDATORY RULES:**\n1. Use the TRADITIONAL form's etymology type (e.g. 'phono-semantic compound', 'pictogram', 'ideogrammic compound')\n2. IGNORE any line that says 'simplified form of X' - that is NOT a valid etymology type\n3. If you see '[{traditional}] Phono-semantic compound...' - use 'phono-semantic compound' as the type\n\n**Wiktionary etymology:**\n{wiktionary_etymology}"
    else:
        user = f"Word: {simplified}"
        user += f"\nPinyin: {pinyin}\nMeaning: {english}"
        if wiktionary_etymology:
            user += f"\n\n**CRITICAL: Use this Wiktionary etymology as your PRIMARY SOURCE:**\n{wiktionary_etymology}"

    try:
        # First API call: etymology/parts with gpt-4o (no examples)
        client = OpenAIClient(model=model)
        system = generate_system_prompt_no_examples(variant)

        if verbose:
            print(f"[chinese] [generate] {simplified} ({variant})...")
        start = time.time()
        data = client.complete_json(system, user, verbose=verbose)

        elapsed = time.time() - start
        if verbose:
            print(f"[chinese] [generated] {simplified} in {elapsed:.1f}s")

        # Second API call: examples with o3-mini (skip if not in contemporary usage)
        if data.get("in_contemporary_usage", True):
            examples_client = OpenAIClient(model="o3-mini")
            examples_system = generate_examples_system_prompt(variant)
            examples_user = f"Generate 2-3 example sentences for:\nWord: {simplified}\nTraditional: {traditional}\nPinyin: {pinyin}\nMeaning: {english}"
            if input_examples and input_examples.strip() and input_examples.strip().lower() != "none":
                examples_user += f"\n\nInclude these examples:\n{input_examples}"

            if verbose:
                print(f"[chinese] [examples] {simplified}...")
            examples_start = time.time()
            examples_data = examples_client.complete_json(examples_system, examples_user, verbose=verbose)
            examples_elapsed = time.time() - examples_start
            if verbose:
                print(f"[chinese] [examples] {simplified} in {examples_elapsed:.1f}s")

            # Merge examples into data
            if examples_data and "examples" in examples_data:
                data["examples"] = examples_data["examples"]
        else:
            if verbose:
                print(f"[chinese] [examples] {simplified} skipped (not in contemporary usage)")
            data["examples"] = []

        if not data or data == {}:
            print(f"[chinese] [ERROR] API returned empty response for {simplified}")
            return {"error": f"API returned empty response for {simplified}"}, simplified, [], [], [], True, False

        # Use schema to extract and transform to cache format
        cache_data = extract_to_cache_format(data, simplified, pinyin, english)

        # Extract values for return
        etymology = cache_data["etymology"]
        api_traditional = cache_data["traditional"] or simplified
        parts_list = _parts_to_tuples(cache_data["parts"])
        examples = _normalize_examples(cache_data["examples"])
        in_contemporary_usage = cache_data["in_contemporary_usage"]

        if is_single:
            components = [(c, t, p, e) for c, t, p, e in parts_list
                         if len(c) == 1 and is_cjk_char(c) and c != simplified]
            char_breakdown = []
        else:
            components = []
            char_breakdown = parts_list

        return etymology, api_traditional, components, char_breakdown, examples, in_contemporary_usage, False

    except Exception as e:
        if verbose:
            print(f"[chinese] [error] Failed to generate content for {simplified}: {e}")
        return {}, simplified, [], [], [], True, False


def _write_single_card(
    parts: List[str],
    simplified: str,
    traditional: str,
    pinyin: str,
    english: str,
    characters: Optional[List[Tuple[str, str, str, str]]] = None,
    components: Optional[List[Tuple[str, str, str, str]]] = None,
    etymology: Optional[Dict[str, str]] = None,
    examples: Optional[List[dict]] = None,
    is_subcard: bool = False,
    breadcrumbs: Optional[List[Tuple[str, str]]] = None,
) -> None:
    """Write a single card section to parts list.

    Uses CHINESE_DISPLAY_SCHEMA to control field order and formatting.
    """
    trad_form = traditional if traditional else simplified
    chinese_heading = f"{simplified}({trad_form})"

    # Header section
    if is_subcard:
        if breadcrumbs:
            breadcrumb_parts = []
            for simp, trad in breadcrumbs:
                trad_form = trad if trad else simp
                breadcrumb_parts.append(f"{simp}({trad_form})")
            breadcrumb_parts.append(chinese_heading)
            breadcrumb_trail = ' → '.join(breadcrumb_parts)
            parts.append(f"### {breadcrumb_trail}")
        else:
            parts.append(f"### {chinese_heading}")
    else:
        parts.append(f"## {chinese_heading}")
        parts.append(FRONT_BACK_DIVIDER)
        parts.append(f"## {english}")
        parts.append(f"### {pinyin}")
        parts.append(FRONT_BACK_DIVIDER)

    # Build field data for display schema
    display_components = characters if (characters and len(characters) > 1) else components
    field_data = {
        "definition": english,
        "pinyin": pinyin,
        "components": display_components if display_components else None,
        "etymology": etymology if (etymology and "error" not in etymology) else None,
        "examples": examples if examples else None,
    }

    # Render fields in display schema order
    for display_field in CHINESE_DISPLAY_SCHEMA:
        value = field_data.get(display_field.name)
        if not value:
            continue

        lines = format_field_for_display(display_field.name, value)
        parts.extend(lines)

    # Handle error separately (not in display schema)
    if etymology and isinstance(etymology, dict) and "error" in etymology:
        parts.append(f"- **error:** {etymology['error']}")


def _generate_recursive_component_cards(
    parts: List[str],
    components: List[Tuple[str, str, str, str]],
    model: Optional[str],
    visited: Set[str],
    depth: int,
    max_depth: int,
    verbose: bool,
    breadcrumbs: Optional[List[Tuple[str, str]]] = None,
    out_dir: Optional[Path] = None,
    parent_word: Optional[str] = None,
    errors: Optional[List[str]] = None,
) -> List[str]:
    """Recursively generate card sections for all component characters."""
    if errors is None:
        errors = []

    if depth > max_depth:
        return errors

    if breadcrumbs is None:
        breadcrumbs = []

    for comp_simp, comp_trad, comp_pin, comp_eng in components:
        if comp_simp in visited:
            continue
        visited.add(comp_simp)

        wiki_ety = fetch_wiktionary_etymology(comp_simp, comp_trad, verbose=verbose)

        comp_etymology, comp_trad_api, sub_components, _, comp_examples, comp_in_contemporary, from_cache = generate_card_content(
            comp_simp, comp_trad, comp_pin, comp_eng,
            wiktionary_etymology=wiki_ety, model=model, verbose=verbose
        )
        comp_trad = comp_trad_api

        if comp_etymology and comp_etymology.get("error"):
            error_msg = comp_etymology.get("error", "Unknown error")
            errors.append(f"{comp_simp}: {error_msg}")
            if out_dir and parent_word:
                add_subcomponent_error(out_dir, parent_word, comp_simp, error_msg)

        if not from_cache:
            save_to_cache(
                comp_simp, comp_simp, comp_trad, comp_pin, comp_eng,
                etymology=comp_etymology, parts=sub_components, examples=comp_examples,
                in_contemporary_usage=comp_in_contemporary, verbose=verbose,
            )

        current_breadcrumbs = breadcrumbs + [(comp_simp, comp_trad)]

        _write_single_card(
            parts,
            simplified=comp_simp,
            traditional=comp_trad,
            pinyin=comp_pin,
            english=comp_eng,
            components=sub_components if sub_components else None,
            etymology=comp_etymology if comp_etymology else None,
            examples=comp_examples if comp_examples else None,
            is_subcard=True,
            breadcrumbs=breadcrumbs,
        )

        if sub_components and depth < max_depth:
            _generate_recursive_component_cards(
                parts, sub_components, model, visited, depth + 1, max_depth, verbose,
                breadcrumbs=current_breadcrumbs,
                out_dir=out_dir,
                parent_word=parent_word,
                errors=errors,
            )

    return errors


def write_card_md(
    out_dir: Path,
    word: str,
    simplified: str,
    traditional: str,
    pinyin: str,
    english: str,
    characters: Optional[List[Tuple[str, str, str, str]]] = None,
    components: Optional[List[Tuple[str, str, str, str]]] = None,
    etymology: Optional[Dict[str, str]] = None,
    examples: Optional[List[dict]] = None,
    model: Optional[str] = None,
    verbose: bool = False,
) -> Tuple[Path, List[str]]:
    """Write a Chinese flashcard markdown file."""
    md_path = out_dir / f"{word}.md"
    parts: List[str] = []
    subcomponent_errors: List[str] = []

    if etymology and etymology.get("error"):
        subcomponent_errors.append(f"{simplified}: {etymology.get('error')}")

    _write_single_card(
        parts,
        simplified=simplified,
        traditional=traditional,
        pinyin=pinyin,
        english=english,
        characters=characters,
        components=components,
        etymology=etymology,
        examples=examples,
    )

    cjk_chars = [ch for ch in simplified if is_cjk_char(ch)]
    visited: Set[str] = {simplified}
    initial_breadcrumb = [(simplified, traditional)]

    if len(cjk_chars) == 1 and components:
        comp_errors = _generate_recursive_component_cards(
            parts, components, model, visited, depth=1, max_depth=5, verbose=verbose,
            breadcrumbs=initial_breadcrumb,
            out_dir=out_dir,
            parent_word=word,
            errors=subcomponent_errors,
        )
        subcomponent_errors = comp_errors
    elif len(cjk_chars) > 1 and characters:
        for ch_simp, ch_trad, ch_pin, ch_eng in characters:
            if ch_simp in visited:
                continue
            visited.add(ch_simp)
            # Each morpheme gets its own visited set for recursive expansion
            morpheme_visited: Set[str] = {simplified, ch_simp}

            morpheme_cjk = [c for c in ch_simp if is_cjk_char(c)]
            is_single_char_morpheme = len(morpheme_cjk) == 1

            ch_wiki_ety = fetch_wiktionary_etymology(ch_simp, ch_trad, verbose=verbose)

            ch_etymology, ch_trad_api, ch_components, ch_char_breakdown, ch_examples, ch_in_contemporary, from_cache = generate_card_content(
                ch_simp, ch_trad, ch_pin, ch_eng,
                wiktionary_etymology=ch_wiki_ety, model=model, verbose=verbose
            )
            ch_trad = ch_trad_api

            if ch_etymology and ch_etymology.get("error"):
                error_msg = ch_etymology.get("error", "Unknown error")
                subcomponent_errors.append(f"{ch_simp}: {error_msg}")
                add_subcomponent_error(out_dir, word, ch_simp, error_msg)

            if not from_cache:
                parts_to_cache = ch_components if is_single_char_morpheme else ch_char_breakdown
                save_to_cache(
                    ch_simp, ch_simp, ch_trad, ch_pin, ch_eng,
                    etymology=ch_etymology,
                    parts=parts_to_cache,
                    examples=ch_examples,
                    in_contemporary_usage=ch_in_contemporary, verbose=verbose,
                )

            morpheme_breadcrumbs = initial_breadcrumb + [(ch_simp, ch_trad)]

            _write_single_card(
                parts,
                simplified=ch_simp,
                traditional=ch_trad,
                pinyin=ch_pin,
                english=ch_eng,
                characters=ch_char_breakdown if not is_single_char_morpheme else None,
                components=ch_components if is_single_char_morpheme else None,
                etymology=ch_etymology if ch_etymology else None,
                examples=ch_examples if ch_examples else None,
                is_subcard=True,
                breadcrumbs=initial_breadcrumb,
            )

            if is_single_char_morpheme and ch_components:
                _generate_recursive_component_cards(
                    parts, ch_components, model, morpheme_visited, depth=2, max_depth=5, verbose=verbose,
                    breadcrumbs=morpheme_breadcrumbs,
                    out_dir=out_dir,
                    parent_word=word,
                    errors=subcomponent_errors,
                )
            elif not is_single_char_morpheme:
                needs_char_breakdown = (
                    not ch_char_breakdown or
                    (len(ch_char_breakdown) == 1 and ch_char_breakdown[0][0] == ch_simp)
                )
                if needs_char_breakdown:
                    ch_char_breakdown = []
                    for char in ch_simp:
                        if is_cjk_char(char):
                            ch_char_breakdown.append((char, char, "", ""))

                for sub_simp, sub_trad, sub_pin, sub_eng in ch_char_breakdown:
                    if sub_simp in morpheme_visited:
                        continue
                    morpheme_visited.add(sub_simp)

                    sub_wiki_ety = fetch_wiktionary_etymology(sub_simp, sub_trad, verbose=verbose)

                    sub_etymology, sub_trad_api, sub_components, _, sub_examples, sub_in_contemporary, sub_from_cache = generate_card_content(
                        sub_simp, sub_trad, sub_pin, sub_eng,
                        wiktionary_etymology=sub_wiki_ety, model=model, verbose=verbose
                    )
                    sub_trad = sub_trad_api

                    if not sub_from_cache:
                        save_to_cache(
                            sub_simp, sub_simp, sub_trad, sub_pin, sub_eng,
                            etymology=sub_etymology, parts=sub_components, examples=sub_examples,
                            in_contemporary_usage=sub_in_contemporary, verbose=verbose,
                        )

                    sub_breadcrumbs = morpheme_breadcrumbs + [(sub_simp, sub_trad)]

                    _write_single_card(
                        parts,
                        simplified=sub_simp,
                        traditional=sub_trad,
                        pinyin=sub_pin,
                        english=sub_eng,
                        components=sub_components if sub_components else None,
                        etymology=sub_etymology if sub_etymology else None,
                        examples=sub_examples if sub_examples else None,
                        is_subcard=True,
                        breadcrumbs=morpheme_breadcrumbs,
                    )

                    if sub_components:
                        _generate_recursive_component_cards(
                            parts, sub_components, model, morpheme_visited, depth=3, max_depth=5, verbose=verbose,
                            breadcrumbs=sub_breadcrumbs,
                            out_dir=out_dir,
                            parent_word=word,
                            errors=subcomponent_errors,
                        )

    # Add footer for main card
    trad_form = traditional if traditional else simplified
    chinese_heading = f"{simplified}({trad_form})"
    parts.append(FRONT_BACK_DIVIDER)
    parts.append(f"## {chinese_heading}")
    parts.append(f"### {pinyin}")
    parts.append(FRONT_BACK_DIVIDER)
    parts.append(f"## {english}")

    content = "\n".join(parts) + "\n"
    md_path.write_text(content, encoding="utf-8")
    if verbose:
        print(f"[chinese] [file] Created card: {md_path.name}")
    return md_path, subcomponent_errors
