"""Unified Chinese flashcard processing.

Simplified processing that:
1. Generates cards with Chinese on front, pinyin/definition/etymology on back
2. Uses OpenAI for character breakdown, etymology, and examples
3. Optionally recurses into component characters when recursive=True
"""

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from lib.schema.base import FRONT_BACK_DIVIDER, CARD_DIVIDER
from lib.common.openai import OpenAIClient
from lib.common.logging import set_thread_log_context, DEFAULT_PARALLEL_WORKERS
from lib.common.manifest import is_word_complete, mark_word_complete, mark_word_in_progress, mark_word_error, init_output_manifest
from lib.common.utils import is_cjk_char


def read_parsed_input(parsed_path: Path) -> List[Tuple[str, str, str, str, str, str]]:
    """Read parsed input CSV file."""
    import csv
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


def generate_etymology(
    simplified: str,
    traditional: str,
    english: str,
    characters: Optional[List[Tuple[str, str, str, str]]] = None,
    model: Optional[str] = None,
) -> Tuple[Dict[str, str], List[Tuple[str, str, str, str]]]:
    """Generate etymology explanation and extract component characters.

    Returns (etymology_dict, list_of_component_tuples).
    Etymology dict has keys: type, description, interpretation.
    Component tuples are (simplified, traditional, pinyin, english).
    For single characters, returns component chars with their info.
    For multi-character words, returns empty component list.
    """
    client = OpenAIClient(model=model)

    char_context = ""
    if characters:
        parts = []
        for ch_simp, ch_trad, ch_pin, ch_eng in characters:
            if ch_trad and ch_trad != ch_simp:
                parts.append(f"{ch_simp}({ch_trad}) [{ch_pin}]: {ch_eng}")
            else:
                parts.append(f"{ch_simp} [{ch_pin}]: {ch_eng}")
        char_context = "\n".join(parts)

    cjk_chars = [ch for ch in simplified if is_cjk_char(ch)]
    is_single = len(cjk_chars) == 1

    if is_single:
        system = """You are an expert in Chinese character etymology.
For this single character, provide:
1. The formation type
2. A brief description of the formation
3. A plain-language interpretation
4. A list of component characters

Return JSON: {
    "type": "pictogram/ideogram/phono-semantic compound/etc.",
    "description": "Brief formation: semantic: X + phonetic: Y",
    "interpretation": "2-3 sentence plain explanation of why/how.",
    "components": [
        {"char": "X", "trad": "X", "pinyin": "pīnyīn", "english": "meaning"},
        ...
    ]
}

CRITICAL FORMAT RULE - When referencing any Chinese character:
- If traditional differs: simplified(traditional) (pinyin, "meaning")
  Example: 华(華) (huá, "Chinese")
- If traditional same as simplified: simplified (pinyin, "meaning")
  Example: 大 (dà, "big")

Rules for each field:
- type: One of: pictogram, ideogram, ideogrammic compound, phono-semantic compound, semantic compound. English only.
- description: Very brief, like "semantic: 金 (jīn, "metal") + phonetic: 艮 (gèn, "tough")." One line.
- interpretation: 2-3 sentences explaining in plain terms. Do NOT start with "The character..."
- components: Only standalone characters (not radicals like 氵). Exclude the headword itself."""
        user = f"Character: {simplified}"
        if traditional and traditional != simplified:
            user += f" (traditional: {traditional})"
        user += f"\nMeaning: {english}"
    else:
        system = """You are an expert in Chinese word etymology.
For this multi-character word, provide a BRIEF explanation of how the component characters combine.

Return JSON: {
    "type": "compound word",
    "description": "Brief: X + Y = meaning",
    "interpretation": "1-2 sentence explanation of semantic connection.",
    "components": []
}

CRITICAL FORMAT RULE - When referencing any Chinese character:
- If traditional differs: simplified(traditional) (pinyin, "meaning")
- If traditional same as simplified: simplified (pinyin, "meaning")

Rules:
- type: Usually "compound word" for multi-character words
- description: Brief combination like "人 (rén, "person") + 口 (kǒu, "mouth")"
- interpretation: 1-2 sentences explaining the semantic connection. Do NOT start with "The word..."
- components: Empty list for multi-character words"""
        user = f"Word: {simplified}"
        if traditional and traditional != simplified:
            user += f" (traditional: {traditional})"
        user += f"\nMeaning: {english}"
        if char_context:
            user += f"\n\nComponent characters:\n{char_context}"

    try:
        data = client.complete_json(system, user)
        ety_type = str(data.get("type", "")).strip()
        ety_desc = str(data.get("description", "")).strip()
        ety_interp = str(data.get("interpretation", "")).strip()
        components_raw = data.get("components", [])

        etymology = {
            "type": ety_type,
            "description": ety_desc,
            "interpretation": ety_interp,
        }

        components: List[Tuple[str, str, str, str]] = []
        if isinstance(components_raw, list):
            for comp in components_raw:
                if isinstance(comp, dict):
                    ch = str(comp.get("char", "")).strip()
                    trad = str(comp.get("trad", ch)).strip()
                    pin = str(comp.get("pinyin", "")).strip()
                    eng = str(comp.get("english", "")).strip()
                    if ch and len(ch) == 1 and is_cjk_char(ch) and ch != simplified:
                        components.append((ch, trad or ch, pin, eng))
                elif isinstance(comp, str) and len(comp) == 1 and is_cjk_char(comp):
                    # Legacy format - just character name
                    if comp != simplified:
                        components.append((comp, comp, "", ""))

        return etymology, components
    except Exception:
        pass
    return {}, []


def generate_character_breakdown(
    simplified: str,
    traditional: str,
    model: Optional[str] = None,
) -> List[Tuple[str, str, str, str]]:
    """Get pinyin and definition for each character in a multi-character word.

    Returns list of (simplified_char, traditional_char, pinyin, english) tuples.
    """
    chars = [ch for ch in simplified if is_cjk_char(ch)]
    if len(chars) <= 1:
        return []

    client = OpenAIClient(model=model)

    system = """For each Chinese character, provide its pinyin and English definitions.
Return JSON: {"characters": [{"char": "X", "trad": "X", "pinyin": "pīnyīn", "english": "def1; def2"}, ...]}

Rules:
1. One entry per character, in order
2. Pinyin must use tone marks (not numbers)
3. English definitions: UP TO 4 of the most common DISTINCT meanings
   - Use SEMICOLON (;) to separate distinct meanings
   - Use COMMA (,) for synonyms of the SAME meaning
   - Fewer definitions is better if additional would be redundant
4. If traditional differs from simplified, include it in "trad"
5. Do NOT censor or filter profanity/vulgarity"""

    user = f"Characters: {' '.join(chars)}"
    if traditional and traditional != simplified:
        user += f"\n(Traditional form of word: {traditional})"

    try:
        data = client.complete_json(system, user)
        chars_data = data.get("characters", [])
        result: List[Tuple[str, str, str, str]] = []
        for item in chars_data:
            if isinstance(item, dict):
                ch = str(item.get("char", "")).strip()
                trad = str(item.get("trad", ch)).strip()
                pin = str(item.get("pinyin", "")).strip()
                eng = str(item.get("english", "")).strip()
                if ch:
                    result.append((ch, trad, pin, eng))
        return result
    except Exception:
        return []


def generate_examples(
    simplified: str,
    traditional: str,
    pinyin: str,
    english: str,
    input_examples: Optional[str] = None,
    model: Optional[str] = None,
) -> List[Tuple[str, str, str]]:
    """Generate example sentences for a vocabulary word.

    Returns list of (chinese, pinyin, english) tuples.
    """
    client = OpenAIClient(model=model)

    word = simplified or traditional
    trad_word = traditional if traditional and traditional != simplified else ""

    system = """Generate example sentences for a Chinese vocabulary word.
Output JSON: {"examples": [{"chinese": "...", "pinyin": "...", "english": "..."}, ...]}

STRUCTURE:
1. Generate ONE ideal example per distinct pronunciation/meaning
   - If pinyin has multiple readings (comma-separated), generate one example for each
   - Each example MUST demonstrate that specific meaning
2. If input examples provided, format ALL of them after the ideal examples

FORMAT for chinese field:
- Show simplified form, with traditional in parentheses after each clause
- Even if identical, include parenthetical: 我吃饭(我吃飯)。
- Split by clause punctuation: 我说话(我說話)，他听(他聽)。

Rules:
- Pinyin must use tone marks
- English should be natural translation
- Do NOT censor profanity/vulgarity"""

    user = f"Word: {word}"
    if trad_word:
        user += f" (traditional: {trad_word})"
    user += f"\nPinyin: {pinyin}\nMeaning(s): {english}"

    if input_examples and input_examples.strip() and input_examples.strip().lower() != "none":
        user += f"\n\nINPUT EXAMPLES (format ALL after ideal examples):\n{input_examples}"
    else:
        user += "\n\nNo input examples - generate 1-2 ideal examples."

    try:
        data = client.complete_json(system, user)
        examples = data.get("examples", [])
        result: List[Tuple[str, str, str]] = []
        if isinstance(examples, list):
            for ex in examples:
                if isinstance(ex, dict):
                    ch = str(ex.get("chinese", "")).strip()
                    pin = str(ex.get("pinyin", "")).strip()
                    eng = str(ex.get("english", "")).strip()
                    if ch:
                        result.append((ch, pin, eng))
        return result
    except Exception:
        return []


def _write_single_card(
    parts: List[str],
    simplified: str,
    traditional: str,
    pinyin: str,
    english: str,
    characters: Optional[List[Tuple[str, str, str, str]]] = None,
    components: Optional[List[Tuple[str, str, str, str]]] = None,
    etymology: Optional[Dict[str, str]] = None,
    examples: Optional[List[Tuple[str, str, str]]] = None,
    is_subcard: bool = False,
    breadcrumbs: Optional[List[str]] = None,
) -> None:
    """Write a single card section to parts list.

    Args:
        is_subcard: If True, this is a recursive sub-card (uses ### heading, no --- divider).
        breadcrumbs: List of Chinese characters showing the path to this sub-component.
    """
    # Build Chinese heading
    if traditional and traditional != simplified:
        chinese_heading = f"{simplified}({traditional})"
    else:
        chinese_heading = simplified

    # Use ### for sub-cards, ## for main cards
    if is_subcard:
        parts.append(f"### {chinese_heading}")
    else:
        parts.append(f"## {chinese_heading}")
        parts.append(FRONT_BACK_DIVIDER)

    # Add breadcrumbs for sub-cards
    if is_subcard and breadcrumbs:
        parts.append(f"- **breadcrumbs:** {' → '.join(breadcrumbs)}")

    parts.append(f"- **pinyin:** {pinyin}")

    # Handle multiple pronunciations with different definitions
    pinyins = [p.strip() for p in pinyin.split(",")]
    definitions = [d.strip() for d in english.split("|")]

    if len(pinyins) > 1 and len(definitions) == len(pinyins):
        parts.append("- **definition:**")
        for pin, defn in zip(pinyins, definitions):
            parts.append(f"  - {pin}: {defn}")
    else:
        parts.append(f"- **definition:** {english}")

    # Character breakdown for multi-character words
    if characters and len(characters) > 1:
        parts.append("- **characters:**")
        for ch_simp, ch_trad, ch_pin, ch_eng in characters:
            if ch_trad and ch_trad != ch_simp:
                parts.append(f"  - {ch_simp}({ch_trad})")
            else:
                parts.append(f"  - {ch_simp}")
            parts.append(f"    - {ch_pin}")
            parts.append(f"    - {ch_eng}")

    # Component breakdown for single characters
    if components:
        parts.append("- **components:**")
        for comp_simp, comp_trad, comp_pin, comp_eng in components:
            if comp_trad and comp_trad != comp_simp:
                parts.append(f"  - {comp_simp}({comp_trad})")
            else:
                parts.append(f"  - {comp_simp}")
            if comp_pin:
                parts.append(f"    - {comp_pin}")
            if comp_eng:
                parts.append(f"    - {comp_eng}")

    # Etymology (structured with type, description, interpretation)
    if etymology and isinstance(etymology, dict):
        ety_type = etymology.get("type", "")
        ety_desc = etymology.get("description", "")
        ety_interp = etymology.get("interpretation", "")
        if ety_type or ety_desc or ety_interp:
            parts.append("- **etymology:**")
            if ety_type:
                parts.append(f"  - **type:** {ety_type}")
            if ety_desc:
                parts.append(f"  - **description:** {ety_desc}")
            if ety_interp:
                parts.append(f"  - **interpretation:** {ety_interp}")

    # Examples
    if examples:
        parts.append("- **examples:**")
        for chinese_part, pinyin_part, english_part in examples:
            parts.append(f"  - {chinese_part}")
            if pinyin_part:
                parts.append(f"    - {pinyin_part}")
            if english_part:
                parts.append(f"    - {english_part}")


def _generate_recursive_component_cards(
    parts: List[str],
    components: List[Tuple[str, str, str, str]],
    model: Optional[str],
    visited: Set[str],
    depth: int,
    max_depth: int,
    verbose: bool,
    breadcrumbs: Optional[List[str]] = None,
) -> None:
    """Recursively generate card sections for all component characters."""
    if depth > max_depth:
        return

    if breadcrumbs is None:
        breadcrumbs = []

    for comp_simp, comp_trad, comp_pin, comp_eng in components:
        if comp_simp in visited:
            continue
        visited.add(comp_simp)

        # Generate etymology for this component (which also gives us its sub-components)
        comp_etymology, sub_components = generate_etymology(
            comp_simp, comp_trad, comp_eng, model=model
        )

        if verbose:
            print(f"[chinese] [api] Got etymology for component {comp_simp}")

        # Current breadcrumbs for this component
        current_breadcrumbs = breadcrumbs + [comp_simp]

        # Write card for this component (as a sub-card)
        _write_single_card(
            parts,
            simplified=comp_simp,
            traditional=comp_trad,
            pinyin=comp_pin,
            english=comp_eng,
            components=sub_components if sub_components else None,
            etymology=comp_etymology if comp_etymology else None,
            is_subcard=True,
            breadcrumbs=breadcrumbs,  # Show parent path, not including self
        )

        # Recursively process sub-components
        if sub_components and depth < max_depth:
            _generate_recursive_component_cards(
                parts, sub_components, model, visited, depth + 1, max_depth, verbose,
                breadcrumbs=current_breadcrumbs,
            )


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
    examples: Optional[List[Tuple[str, str, str]]] = None,
    recursive: bool = False,
    model: Optional[str] = None,
    verbose: bool = False,
) -> Path:
    """Write a Chinese flashcard markdown file.

    If recursive=True and this is a single character with components,
    generates additional card sections for each component (and sub-components).
    """
    md_path = out_dir / f"{word}.md"
    parts: List[str] = []

    # Write the main card
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

    # If recursive, generate cards for components/characters
    cjk_chars = [ch for ch in simplified if is_cjk_char(ch)]
    visited: Set[str] = {simplified}

    if recursive:
        # Initial breadcrumb is the main word
        initial_breadcrumb = [simplified]

        if len(cjk_chars) == 1 and components:
            # Single character: recurse into components
            _generate_recursive_component_cards(
                parts, components, model, visited, depth=1, max_depth=5, verbose=verbose,
                breadcrumbs=initial_breadcrumb,
            )
        elif len(cjk_chars) > 1 and characters:
            # Multi-character word: recurse into each character
            for ch_simp, ch_trad, ch_pin, ch_eng in characters:
                if ch_simp in visited:
                    continue
                visited.add(ch_simp)

                # Generate etymology for this character
                ch_etymology, ch_components = generate_etymology(ch_simp, ch_trad, ch_eng, model=model)
                if verbose:
                    print(f"[chinese] [api] Got etymology for character {ch_simp}")

                # Breadcrumbs for this character
                char_breadcrumbs = initial_breadcrumb + [ch_simp]

                # Write card for this character (as sub-card)
                _write_single_card(
                    parts,
                    simplified=ch_simp,
                    traditional=ch_trad,
                    pinyin=ch_pin,
                    english=ch_eng,
                    components=ch_components if ch_components else None,
                    etymology=ch_etymology if ch_etymology else None,
                    is_subcard=True,
                    breadcrumbs=initial_breadcrumb,  # Show parent (the word)
                )

                # Recursively process this character's components
                if ch_components:
                    _generate_recursive_component_cards(
                        parts, ch_components, model, visited, depth=2, max_depth=5, verbose=verbose,
                        breadcrumbs=char_breadcrumbs,
                    )

    # Add card divider at the very end, after all recursive content
    parts.append(CARD_DIVIDER)

    content = "\n".join(parts) + "\n"
    md_path.write_text(content, encoding="utf-8")
    if verbose:
        print(f"[chinese] [file] Created card: {md_path.name}")
    return md_path


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
    recursive: bool = False,
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
        # Generate character breakdown for multi-character words
        characters = None
        cjk_chars = [ch for ch in (simp or headword) if is_cjk_char(ch)]
        if len(cjk_chars) > 1:
            characters = generate_character_breakdown(simp, trad, model=model)
            if verbose and characters:
                print(f"[chinese] [api] Got {len(characters)} character breakdown(s) for {headword}")

        # Generate etymology and get component characters
        etymology, components = generate_etymology(simp, trad, eng, characters=characters, model=model)
        if verbose and etymology:
            print(f"[chinese] [api] Got etymology for {headword}")
        if verbose and components:
            print(f"[chinese] [api] Got {len(components)} component(s) for {headword}")

        # Generate example sentences
        input_examples = phrase if phrase and phrase.strip() and phrase.strip().lower() != "none" else None
        examples = generate_examples(simp, trad, pin, eng, input_examples=input_examples, model=model)
        if verbose and examples:
            print(f"[chinese] [api] Got {len(examples)} example(s) for {headword}")

        # Write card (handles recursive component generation internally)
        write_card_md(
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
            recursive=recursive,
            model=model,
            verbose=verbose,
        )

        # Mark complete
        mark_word_complete(out_dir, file_base)

        if verbose:
            print(f"[chinese] [ok] Card created: {file_base}")
        return 1, 1

    except Exception as e:
        # Mark as error
        mark_word_error(out_dir, file_base)
        if verbose:
            print(f"[chinese] [error] Failed to generate card for {file_base}: {e}")
        raise


def process_chinese_folder(
    folder: Path,
    model: Optional[str] = None,
    recursive: bool = False,
    verbose: bool = False,
    chunk_range: Optional[Tuple[int, int]] = None,
) -> Tuple[int, int]:
    """Process a folder of Chinese vocabulary words.

    Args:
        folder: Output folder for generated cards
        model: OpenAI model name
        recursive: Whether to recursively generate component cards
        verbose: Enable verbose logging
        chunk_range: If specified, process only words from those chunks

    Returns (total_words, cards_created) tuple.
    """
    out_dir = folder

    # Read input
    parsed_path = folder / "-input.parsed.csv"
    if not parsed_path.exists():
        # Try chunk CSVs
        all_rows = _read_all_chunk_csvs(folder)
    else:
        rows = read_parsed_input(parsed_path)
        # Skip sub-words (relation field not empty)
        all_rows = [(idx, 0, s, t, p, e, ph, r) for idx, (s, t, p, e, ph, r) in enumerate(rows, start=1) if not r.strip()]

    if not all_rows:
        if verbose:
            print(f"[chinese] [skip] No parsed input in {folder}")
        return 0, 0

    # Initialize manifest
    word_keys = [f"{idx}.{simp or trad}" for idx, _, simp, trad, _, _, _, _ in all_rows]
    init_output_manifest(out_dir, word_keys)

    # Filter by chunk range if specified
    if chunk_range:
        start_chunk, end_chunk = chunk_range
        rows_to_process = [(idx, s, t, p, e, ph, r) for idx, chunk_num, s, t, p, e, ph, r in all_rows
                          if start_chunk <= chunk_num <= end_chunk]
    else:
        rows_to_process = [(idx, s, t, p, e, ph, r) for idx, _, s, t, p, e, ph, r in all_rows]

    if verbose:
        print(f"[chinese] [info] Processing {len(rows_to_process)} vocabulary words from {folder.name}/")
        if recursive:
            print(f"[chinese] [info] Recursive mode enabled - will generate component cards")

    total_cards = 0
    workers = DEFAULT_PARALLEL_WORKERS

    if workers == 1:
        for idx, simp, trad, pin, eng, phrase, rel in rows_to_process:
            try:
                _, inc = process_chinese_row(
                    folder, idx, simp, trad, pin, eng, phrase, rel, model, recursive, verbose
                )
                total_cards += inc
            except Exception as e:
                if verbose:
                    print(f"[chinese] [error] Failed to build card for {(simp or trad)}: {e}")
                raise
    else:
        if verbose:
            print(f"[chinese] [info] Parallel workers: {workers}")
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = []
            for idx, simp, trad, pin, eng, phrase, rel in rows_to_process:
                futures.append(
                    executor.submit(
                        process_chinese_row,
                        folder, idx, simp, trad, pin, eng, phrase, rel, model, recursive, verbose
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
    _write_combined_output(out_dir, verbose, chunk_range=chunk_range)

    return len(rows_to_process), total_cards


def _read_all_chunk_csvs(folder: Path) -> List[Tuple[int, int, str, str, str, str, str, str]]:
    """Read ALL parsed chunk CSVs and return rows with global indices."""
    all_rows: List[Tuple[int, int, str, str, str, str, str, str]] = []

    chunk_files = sorted(folder.glob("-input.parsed.*.csv"))

    global_idx = 0
    for chunk_file in chunk_files:
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
            all_rows.append((global_idx, chunk_num, simp, trad, pin, eng, phrase, rel))

    return all_rows


def _write_combined_output(out_dir: Path, verbose: bool = False, chunk_range: Optional[Tuple[int, int]] = None) -> None:
    """Concatenate all .md files into -output.md."""
    try:
        if chunk_range:
            output_name = f"-output.{chunk_range[0]:03d}-{chunk_range[1]:03d}.md"
        else:
            output_name = "-output.md"
        output_md = out_dir / output_name

        md_files = [p for p in sorted(out_dir.glob("*.md")) if not p.name.startswith("-output")]
        parts: List[str] = []
        for p in md_files:
            try:
                parts.append(p.read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                if verbose:
                    print(f"[chinese] [warn] failed reading {p.name} for {output_name}")
        content = "\n\n".join(parts) + ("\n" if parts else "")
        output_md.write_text(content, encoding="utf-8")
        if verbose:
            print(f"[chinese] [ok] Wrote {output_name} ({len(content)} bytes) with {len(md_files)} files")
    except Exception as e:
        if verbose:
            print(f"[chinese] [warn] failed to write output: {e}")
