"""Chinese flashcard content generation and markdown writing."""

import csv
import re
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
from lib.common import get_llm_client, add_subcomponent_error, is_cjk_char, key_lock, collapse_identical_parens

from lib.output.chinese.cache import read_cache, write_cache
from lib.output.chinese.wiktionary import fetch_wiktionary_etymology

# Glyph-progression images (built by scripts/glyph_progression.py) live here and
# are referenced from a card as ![](@media/glyph<codepoint>.png); mochi_sync
# uploads the matching file as a Mochi attachment.
MEDIA_DIR = Path(__file__).parent.parent.parent.parent / "output" / "chinese" / "media"


# A component's definition must be its MEANING, never the ROLE it plays in the
# parent (a phono-semantic compound). Older cards/caches sometimes stored the
# role ("phonetic", "phonetic sound", "used phonetic", ...) as the gloss; treat
# those as no-meaning and fall back to the character's own cached meaning. Keyed
# on a leading role descriptor so legitimate meanings (响 = "sound") are kept.
_ROLE_RE = re.compile(
    r"^(used\s+|the\s+|a\s+|acts?\s+as\s+|serves?\s+as\s+)?"
    r"(phonetic|semantic|phono-?semantic"
    r"|sound\s+(component|element|part)"
    r"|ideographic\s+(component|element))\b",
    re.IGNORECASE,
)


def _is_role_word(eng: str) -> bool:
    e = re.sub(r"\([^)]*\)", "", eng or "").strip().strip(".")
    return not e or bool(_ROLE_RE.match(e))


def _clean_definition(simplified: str, english: str) -> str:
    """Return a real meaning for a component, never a bare role word.

    If `english` is a role word (or empty), fall back to the character's own
    cached meaning; if that is also unusable, return "" so the definition line
    is simply omitted rather than showing 'phonetic'."""
    if english and not _is_role_word(english):
        return english
    if len(simplified) == 1 and is_cjk_char(simplified):
        cached = read_cache(simplified) or {}
        ce = str(cached.get("english", "")).strip()
        if ce and not _is_role_word(ce):
            return ce
    return ""


def _clean_pinyin(simplified: str, pinyin: str) -> str:
    """A component subcard shows the pinyin passed from the parent's parts, which
    is sometimes empty even when the character's own card has it; fall back to the
    cached pinyin."""
    if pinyin and pinyin.strip():
        return pinyin
    if len(simplified) == 1 and is_cjk_char(simplified):
        cp = str((read_cache(simplified) or {}).get("pinyin", "")).strip()
        if cp:
            return cp
    return pinyin


# Old Chinese reconstructions ("(OC *laŋ)", ", OC *m-tʰaːʔ") must never appear in
# output (the prompt forbids them, but they occasionally leak). Strip at render
# so a re-render scrubs existing cards.
def _strip_oc(text: str) -> str:
    if not text:
        return text
    t = re.sub(r"\s*\(\s*OC\b[^)]*\)", "", text)          # standalone "(OC *…)"
    t = re.sub(r",?\s*\bOC\s*\*[^),;]+", "", t)            # embedded "…, OC *…"
    return re.sub(r"\s{2,}", " ", t).strip()


def _sanitize_etymology(etym):
    """Strip OC reconstructions from every etymology sub-field."""
    if not isinstance(etym, dict):
        return etym
    return {k: (_strip_oc(v) if isinstance(v, str) else v) for k, v in etym.items()}


def _clean_components(comps):
    """Clean each component's gloss: drop role words (fall back to the char's real
    meaning) and strip OC reconstructions — the parent's component list isn't
    cleaned by `_clean_definition` (which only handles a subcard's own definition)."""
    if not comps:
        return comps
    out = []
    for it in comps:
        if isinstance(it, (list, tuple)) and len(it) >= 4:
            gloss = _strip_oc(_clean_definition(str(it[0]), str(it[3])))
            out.append((it[0], it[1], it[2], gloss, *it[4:]))
        else:
            out.append(it)
    return out


def _progression_lines(simplified: str) -> List[str]:
    """Markdown for a single character's historical-forms image, if one exists."""
    if len(simplified) != 1 or not is_cjk_char(simplified):
        return []
    fname = f"glyph{ord(simplified):x}.png"
    if not (MEDIA_DIR / fname).exists():
        return []
    return ["- **historical forms:**", "", f"![Historical forms of {simplified}](@media/{fname})"]


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
    model: Optional[str] = None,
    verbose: bool = False,
) -> Tuple[Dict[str, str], str, List[Tuple[str, str, str, str]], List[Tuple[str, str, str, str]], List[dict], bool, bool]:
    """Generate all card content in a single API call.

    Wiktionary etymology is fetched lazily (only on a cache miss). The whole
    read -> fetch -> generate -> write sequence is serialized per word via
    ``key_lock`` so parallel workers never redundantly regenerate (and pay for)
    the same shared component.

    Returns (etymology_dict, traditional, components, character_breakdown, examples, in_contemporary_usage, from_cache).
    """
    word = simplified or traditional
    # A component may arrive glossed by its ROLE ("phonetic") rather than its
    # meaning; don't feed that into the prompt or persist it to cache.
    english = _clean_definition(simplified, english)
    cjk_chars = [ch for ch in simplified if is_cjk_char(ch)]
    is_single = len(cjk_chars) == 1

    # Serialize generation of this specific word/component across threads.
    with key_lock(word):
        # Check cache first (now memoized in-process, so this is cheap).
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

        # Cache miss: only now do we hit Wiktionary (avoids wasted network/IO
        # for words that were already cached).
        wiktionary_etymology = fetch_wiktionary_etymology(
            simplified or word, traditional or word,
            pinyin=pinyin, english=english, model=model, verbose=verbose
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
            # First API call: etymology/parts (no examples)
            client = get_llm_client(model=model)
            system = generate_system_prompt_no_examples(variant)

            if verbose:
                print(f"[chinese] [generate] {simplified} ({variant})...")
            start = time.time()
            data = client.complete_json(system, user, verbose=verbose)

            elapsed = time.time() - start
            if verbose:
                print(f"[chinese] [generated] {simplified} in {elapsed:.1f}s")

            # Second API call: examples (skip if not in contemporary usage).
            # Uses the same model as the rest of the pipeline (respects --model)
            # instead of a hardcoded reasoning model.
            if data.get("in_contemporary_usage", True):
                examples_client = get_llm_client(model=model)
                examples_system = generate_examples_system_prompt(variant)
                examples_user = f"Generate 2-3 example sentences for:\nWord: {simplified}\nTraditional: {traditional}\nPinyin: {pinyin}\nMeaning: {english}"
                if input_examples and input_examples.strip() and input_examples.strip().lower() != "none":
                    examples_user += (
                        f"\n\nPRESERVE this provided example VERBATIM as the FIRST example sentence - "
                        f"keep its exact wording, do NOT paraphrase, replace, or drop it. Only add the "
                        f"required (traditional) annotation and tone-marked pinyin, then add 1-2 more of "
                        f"your own:\n{input_examples}"
                    )

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

            # Persist to cache inside the lock so a waiting thread for the same
            # word gets a cache hit instead of regenerating.
            fresh_parts = components if components else char_breakdown
            save_to_cache(
                word, simplified or word, api_traditional, pinyin, english,
                etymology=etymology, parts=fresh_parts, examples=examples,
                in_contemporary_usage=in_contemporary_usage, verbose=verbose,
            )

            # Build this character's glyph-progression image inline (best-effort,
            # cached) so it's part of normal generation, not a separate step.
            if is_single:
                from lib.output.chinese.glyph import build_progression
                build_progression(simplified)

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
    english = _strip_oc(_clean_definition(simplified, english))
    pinyin = _clean_pinyin(simplified, pinyin)
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
        # Only surface a traditional field when the form actually differs.
        "traditional": traditional if (traditional and traditional != simplified) else None,
        "definition": english,
        "pinyin": pinyin,
        "components": _clean_components(display_components) if display_components else None,
        "etymology": _sanitize_etymology(etymology) if (etymology and "error" not in etymology) else None,
        "examples": examples if examples else None,
    }

    # Render fields in display schema order
    for display_field in CHINESE_DISPLAY_SCHEMA:
        value = field_data.get(display_field.name)
        if not value:
            continue

        lines = format_field_for_display(display_field.name, value)
        parts.extend(lines)

    # Historical-forms (glyph progression) image for single-character sections.
    parts.extend(_progression_lines(simplified))

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

        comp_etymology, comp_trad_api, sub_components, _, comp_examples, comp_in_contemporary, from_cache = generate_card_content(
            comp_simp, comp_trad, comp_pin, comp_eng,
            model=model, verbose=verbose
        )
        comp_trad = comp_trad_api

        if comp_etymology and comp_etymology.get("error"):
            error_msg = comp_etymology.get("error", "Unknown error")
            errors.append(f"{comp_simp}: {error_msg}")
            if out_dir and parent_word:
                add_subcomponent_error(out_dir, parent_word, comp_simp, error_msg)

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

            ch_etymology, ch_trad_api, ch_components, ch_char_breakdown, ch_examples, ch_in_contemporary, from_cache = generate_card_content(
                ch_simp, ch_trad, ch_pin, ch_eng,
                model=model, verbose=verbose
            )
            ch_trad = ch_trad_api

            if ch_etymology and ch_etymology.get("error"):
                error_msg = ch_etymology.get("error", "Unknown error")
                subcomponent_errors.append(f"{ch_simp}: {error_msg}")
                add_subcomponent_error(out_dir, word, ch_simp, error_msg)

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

                    sub_etymology, sub_trad_api, sub_components, _, sub_examples, sub_in_contemporary, sub_from_cache = generate_card_content(
                        sub_simp, sub_trad, sub_pin, sub_eng,
                        model=model, verbose=verbose
                    )
                    sub_trad = sub_trad_api

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

    # Mochi renders 字(繁) as furigana (繁 above 字). To keep the baseline evenly
    # spaced, EVERY character needs a furigana box: differing chars get 字(繁),
    # identical chars an empty 字( ) (renders as whitespace above the char in
    # Mochi — invisible there, only the raw markdown shows the parens). Without
    # the empty slots the annotated chars render wider and the line misaligns.
    # Fully-identical runs still collapse to bare (糸(糸) -> 糸).
    rendered = [
        collapse_identical_parens(line, empty_slots=True)
        for line in "\n".join(parts).split("\n")
    ]
    content = "\n".join(rendered) + "\n"
    md_path.write_text(content, encoding="utf-8")
    if verbose:
        print(f"[chinese] [file] Created card: {md_path.name}")
    return md_path, subcomponent_errors
