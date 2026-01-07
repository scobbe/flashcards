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

import json
import requests
from bs4 import BeautifulSoup

from lib.schema.base import FRONT_BACK_DIVIDER, CARD_DIVIDER
from lib.common.openai import OpenAIClient, CHINESE_SINGLE_CHAR_SCHEMA, CHINESE_MULTI_CHAR_SCHEMA
from lib.common.logging import set_thread_log_context, DEFAULT_PARALLEL_WORKERS
from lib.common.manifest import is_word_complete, mark_word_complete, mark_word_in_progress, mark_word_error, init_output_manifest, add_subcomponent_error
from lib.common.utils import is_cjk_char

# Global cache directory for card data
CARD_CACHE_DIR = Path(__file__).parent.parent.parent / "output" / "chinese" / "cache"


def _get_cache_path(word: str) -> Path:
    """Get the cache file path for a word/character."""
    return CARD_CACHE_DIR / f"{word}.json"


def _read_cache(word: str, verbose: bool = False) -> Optional[Dict]:
    """Read cached data for a word/character. Returns None if not cached."""
    cache_path = _get_cache_path(word)
    if not cache_path.exists():
        return None
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        if verbose:
            print(f"[cache] [read] Loaded from cache: {word}")
        return data
    except Exception:
        return None


def _write_cache(word: str, data: Dict, verbose: bool = False) -> None:
    """Write data to cache."""
    CARD_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = _get_cache_path(word)
    cache_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if verbose:
        print(f"[cache] [write] Saved to cache: {word}")


def _read_etymology_from_cache(data: Dict) -> Tuple[Dict[str, str], List[Tuple[str, str, str, str]]]:
    """Extract etymology and components/parts from cached data."""
    etymology = {
        "type": data.get("etymology", {}).get("type", ""),
        "description": data.get("etymology", {}).get("description", ""),
        "interpretation": data.get("etymology", {}).get("interpretation", ""),
        "simplification": data.get("etymology", {}).get("simplification", ""),
    }
    # Check both "parts" (new unified field) and "components" (legacy)
    parts_data = data.get("parts", data.get("components", []))
    components = []
    for comp in parts_data:
        if isinstance(comp, dict):
            components.append((
                comp.get("char", ""),
                comp.get("trad", ""),
                comp.get("pinyin", ""),
                comp.get("english", ""),
            ))
    return etymology, components


def _extract_etymology_from_html(html: str) -> str:
    """Extract ONLY the descriptive paragraph text from Glyph origin section.

    Excludes: historical forms tables, phonetic series boxes, and Etymology section.
    Only returns paragraph text describing the character's pictographic origin.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Find main content
    content = soup.find("div", {"id": "mw-content-text"})
    if not content:
        return ""

    # Find "Glyph origin" heading only
    heading = content.find(
        lambda tag: tag.name in ["h2", "h3", "h4", "h5"]
        and "glyph origin" in tag.get_text().lower()
    )
    if not heading:
        # Try mw-heading div
        for heading_div in content.find_all("div", class_=lambda x: x and "mw-heading" in x if x else False):
            if heading_div.find(string=lambda s: s and "glyph origin" in s.lower() if s else False):
                heading = heading_div
                break

    if not heading:
        return ""

    # Get container (might be mw-heading div or the heading itself)
    container = heading.parent if heading.parent and heading.parent.name == "div" else heading

    # Collect ONLY paragraph text until next heading
    section_text = []
    for sibling in container.find_next_siblings():
        # Stop at next heading
        if sibling.name in ["h2", "h3", "h4", "h5"]:
            break
        if sibling.find(["h2", "h3", "h4"]):
            break
        # Skip tables (historical forms)
        if sibling.name == "table":
            continue
        # Skip NavFrame/collapsible boxes (phonetic series)
        if sibling.get("class"):
            classes = " ".join(sibling.get("class", []))
            if any(skip in classes for skip in ["NavFrame", "navbox", "catlinks", "mw-collapsible"]):
                continue
        # Only extract from paragraph tags
        if sibling.name == "p":
            text = sibling.get_text(separator=" ", strip=True)
            if text and len(text) > 5:
                # Clean up
                text = re.sub(r'\[edit\]', '', text, flags=re.IGNORECASE)
                text = re.sub(r'\s+', ' ', text).strip()
                if text:
                    section_text.append(text)

    return "\n".join(section_text)


def fetch_wiktionary_etymology(simplified: str, traditional: str = "", verbose: bool = False) -> str:
    """Fetch and extract ONLY etymology/glyph origin from Wiktionary.

    Fetches BOTH simplified and traditional forms if they differ.
    Saves to cache directory as {word}.etymology.txt alongside the JSON cache.
    Returns the combined etymology text, or empty string if not found.
    """
    CARD_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # Determine which words to fetch
    words_to_fetch = [simplified]
    if traditional and traditional != simplified:
        words_to_fetch.append(traditional)

    # Build cache key from all words
    cache_key = simplified if not traditional or traditional == simplified else f"{simplified}_{traditional}"
    cache_path = CARD_CACHE_DIR / f"{cache_key}.etymology.txt"

    # Check cache first
    if cache_path.exists():
        try:
            content = cache_path.read_text(encoding="utf-8").strip()
            if content:
                if verbose:
                    print(f"[wiktionary] [cache] {cache_key}")
                return content
        except Exception:
            pass

    all_etymology_parts = []

    for word in words_to_fetch:
        # Fetch from Wiktionary
        url = f"https://en.wiktionary.org/wiki/{requests.utils.requote_uri(word)}"
        try:
            resp = requests.get(url, timeout=20, headers={
                "User-Agent": "flashcards-script/1.0"
            })
            if resp.status_code != 200:
                if verbose:
                    print(f"[wiktionary] [skip] {word}: status {resp.status_code}")
                continue
        except Exception as e:
            if verbose:
                print(f"[wiktionary] [error] {word}: {e}")
            continue

        if verbose:
            print(f"[wiktionary] [fetch] {word}")

        # Extract etymology
        etymology = _extract_etymology_from_html(resp.text)
        if etymology:
            # Add word label if fetching multiple
            if len(words_to_fetch) > 1:
                all_etymology_parts.append(f"[{word}]\n{etymology}")
            else:
                all_etymology_parts.append(etymology)

    # Combine and truncate
    result = "\n\n".join(all_etymology_parts)
    if len(result) > 3000:
        result = result[:3000] + "..."

    # Save to cache
    if result:
        cache_path.write_text(result, encoding="utf-8")

    return result


def _write_complete_cache(
    word: str,
    simplified: str,
    traditional: str,
    pinyin: str,
    english: str,
    etymology: Optional[Dict[str, str]] = None,
    components: Optional[List[Tuple[str, str, str, str]]] = None,
    character_breakdown: Optional[List[Tuple[str, str, str, str]]] = None,
    examples: Optional[List[Tuple[str, str, str]]] = None,
    verbose: bool = False,
) -> None:
    """Write complete cache entry with all data. Only writes if examples exist."""
    # Check for error state in etymology
    if etymology and etymology.get("error"):
        print(f"[cache] [ERROR] Not caching {word} - API error: {etymology.get('error')}")
        return

    if not examples:
        # This is an error state - API should always return examples for valid characters
        print(f"[cache] [ERROR] Not caching {word} - no examples returned (possible API failure)")
        return

    cache_data: Dict = {
        "simplified": simplified,
        "traditional": traditional,
        "pinyin": pinyin,
        "english": english,
    }

    if etymology:
        cache_data["etymology"] = etymology

    # Use unified "parts" field - either components (single char) or character_breakdown (multi-char)
    parts = components or character_breakdown
    if parts:
        cache_data["parts"] = [
            {"char": c[0], "trad": c[1], "pinyin": c[2], "english": c[3]}
            for c in parts
        ]

    if examples:
        cache_data["examples"] = [
            {"chinese": e[0], "pinyin": e[1], "english": e[2]}
            for e in examples
        ]

    _write_cache(word, cache_data, verbose=verbose)


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


def generate_card_content(
    simplified: str,
    traditional: str,
    pinyin: str,
    english: str,
    input_examples: Optional[str] = None,
    wiktionary_etymology: Optional[str] = None,
    model: Optional[str] = None,
    verbose: bool = False,
) -> Tuple[Dict[str, str], List[Tuple[str, str, str, str]], List[Tuple[str, str, str, str]], List[Tuple[str, str, str]], bool]:
    """Generate all card content in a single API call.

    Returns (etymology_dict, components, character_breakdown, examples, from_cache).
    - etymology_dict: {type, description, interpretation}
    - components: For single chars, list of (simp, trad, pinyin, english) component tuples
    - character_breakdown: For multi-char words, list of (simp, trad, pinyin, english) for each char
    - examples: list of (chinese, pinyin, english) example sentence tuples
    - from_cache: True if data was loaded from cache, False if newly generated
    """
    word = simplified or traditional
    cjk_chars = [ch for ch in simplified if is_cjk_char(ch)]
    is_single = len(cjk_chars) == 1

    # Check cache first - must have ALL required fields
    cached = _read_cache(word, verbose=verbose)
    required_fields = ["etymology", "examples", "pinyin", "english"]
    if cached is not None and all(f in cached for f in required_fields):
        etymology, parts = _read_etymology_from_cache(cached)
        # For single chars: parts are components; for multi-char: parts are character breakdown
        if is_single:
            components = parts
            char_breakdown = []
        else:
            components = []
            char_breakdown = parts
        # Read examples
        examples = []
        for ex in cached.get("examples", []):
            if isinstance(ex, dict):
                examples.append((
                    ex.get("chinese", ""),
                    ex.get("pinyin", ""),
                    ex.get("english", ""),
                ))
        return etymology, components, char_breakdown, examples, True  # from_cache=True

    client = OpenAIClient(model=model)

    # Use shorter prompts with structured outputs - schema enforces format
    # Etymology: type & description from Wiktionary, interpretation is LLM's own explanation
    if is_single:
        system = """Chinese character etymology expert. Return JSON with these fields:
- type: Extract formation type directly from Wiktionary (pictogram, ideogram, phono-semantic compound, etc.)
- description: Extract brief formation info from Wiktionary (e.g. "semantic: X + phonetic: Y")
- interpretation: Your own 2-3 sentence explanation based on the description. Don't start with "The character..."
- simplification: Why this was simplified (intuition/reasoning), or "none" if traditional = simplified
- parts: array of component chars [{char, trad, pinyin, english}], standalone chars only (not radicals like 氵), exclude headword
- examples: array of 2-3 sentences [{chinese, pinyin, english}], format: each clause 简体(繁體) with period inside final paren, e.g. 我吃饭(我吃飯)。 or 秋收时(秋收時)，农夫割草(農夫割草)。"""
        user = f"Character: {simplified}"
        if traditional and traditional != simplified:
            user += f" (trad: {traditional})"
        user += f"\nPinyin: {pinyin}\nMeaning: {english}"
        if wiktionary_etymology:
            user += f"\n\n**PRIMARY SOURCE for type & description** - Wiktionary glyph origin:\n{wiktionary_etymology}"
    else:
        system = """Chinese word etymology expert. Return JSON with these fields:
- type: Usually "compound word"
- description: Brief word formation (e.g. "X + Y = meaning")
- interpretation: 1-2 sentences, don't start with "The word..."
- simplification: Why this word was simplified (intuition), or "none" if traditional = simplified
- parts: array of character breakdown [{char, trad, pinyin, english}], each char's pinyin (tone marks) and up to 4 meanings (semicolon-separated)
- examples: array of 2-3 sentences [{chinese, pinyin, english}], format: each clause 简体(繁體) with period inside final paren, e.g. 我吃饭(我吃飯)。 or 秋收时(秋收時)，农夫割草(農夫割草)。"""
        user = f"Word: {simplified}"
        if traditional and traditional != simplified:
            user += f" (trad: {traditional})"
        user += f"\nPinyin: {pinyin}\nMeaning: {english}"
        if wiktionary_etymology:
            user += f"\n\nWiktionary ref:\n{wiktionary_etymology}"

    if input_examples and input_examples.strip() and input_examples.strip().lower() != "none":
        user += f"\n\nInclude examples:\n{input_examples}"

    try:
        data = client.complete_json(system, user, verbose=verbose)

        # Check for empty response - this is an error, not a legitimate "no content" case
        if not data or data == {}:
            print(f"[chinese] [ERROR] API returned empty response for {simplified}")
            # Return error indicator in etymology
            return {"error": f"API returned empty response for {simplified}"}, [], [], [], False

        # Parse etymology (includes simplification reasoning)
        simplification = str(data.get("simplification", "")).strip()
        etymology = {
            "type": str(data.get("type", "")).strip(),
            "description": str(data.get("description", "")).strip(),
            "interpretation": str(data.get("interpretation", "")).strip(),
            "simplification": simplification if simplification.lower() != "none" else "",
        }

        # Parse parts - unified field for both components (single char) and characters (multi-char)
        parts_list: List[Tuple[str, str, str, str]] = []
        for part in data.get("parts", []):
            if isinstance(part, dict):
                ch = str(part.get("char", "")).strip()
                trad = str(part.get("trad", ch)).strip()
                pin = str(part.get("pinyin", "")).strip()
                eng = str(part.get("english", "")).strip()
                if ch:
                    parts_list.append((ch, trad or ch, pin, eng))

        # For single chars: parts are components, no character breakdown
        # For multi-char: parts are character breakdown, no components
        if is_single:
            # Filter to only valid single CJK chars that aren't the headword
            components = [(c, t, p, e) for c, t, p, e in parts_list
                         if len(c) == 1 and is_cjk_char(c) and c != simplified]
            char_breakdown = []
        else:
            components = []
            char_breakdown = parts_list

        # Parse examples
        examples: List[Tuple[str, str, str]] = []
        for ex in data.get("examples", []):
            if isinstance(ex, dict):
                ch = str(ex.get("chinese", "")).strip()
                pin = str(ex.get("pinyin", "")).strip()
                eng = str(ex.get("english", "")).strip()
                if ch:
                    examples.append((ch, pin, eng))

        return etymology, components, char_breakdown, examples, False  # from_cache=False

    except Exception as e:
        if verbose:
            print(f"[chinese] [error] Failed to generate content for {simplified}: {e}")
        return {}, [], [], [], False


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
    breadcrumbs: Optional[List[Tuple[str, str]]] = None,
) -> None:
    """Write a single card section to parts list.

    Args:
        is_subcard: If True, this is a recursive sub-card (uses ### heading, no --- divider).
        breadcrumbs: List of (simplified, traditional) tuples showing the path to this sub-component.
    """
    # Build Chinese heading with traditional in parens if different
    if traditional and traditional != simplified:
        chinese_heading = f"{simplified}({traditional})"
    else:
        chinese_heading = simplified

    # Use ### for sub-cards, ## for main cards
    if is_subcard:
        if breadcrumbs:
            # Build breadcrumb trail with traditional forms: 西门町(西門町) → 门(門)
            breadcrumb_parts = []
            for simp, trad in breadcrumbs:
                if trad and trad != simp:
                    breadcrumb_parts.append(f"{simp}({trad})")
                else:
                    breadcrumb_parts.append(simp)
            # Add current character with traditional
            breadcrumb_parts.append(chinese_heading)
            breadcrumb_trail = ' → '.join(breadcrumb_parts)
            parts.append(f"### {breadcrumb_trail}")
        else:
            parts.append(f"### {chinese_heading}")
    else:
        # Main card front: Chinese, ---, English, Pinyin, ---
        parts.append(f"## {chinese_heading}")
        parts.append(FRONT_BACK_DIVIDER)
        parts.append(f"## {english}")
        parts.append(f"### {pinyin}")
        parts.append(FRONT_BACK_DIVIDER)

    # Definition and pinyin as bullet points (order: definition, pinyin)
    pinyins = [p.strip() for p in pinyin.split(",")]
    definitions = [d.strip() for d in english.split("|")]

    if len(pinyins) > 1 and len(definitions) == len(pinyins):
        parts.append("- **definition:**")
        for pin, defn in zip(pinyins, definitions):
            parts.append(f"  - {pin}: {defn}")
    else:
        parts.append(f"- **definition:** {english}")

    parts.append(f"- **pinyin:** {pinyin}")

    # Components (for both multi-character words and single characters)
    if characters and len(characters) > 1:
        parts.append("- **components:**")
        for ch_simp, ch_trad, ch_pin, ch_eng in characters:
            if ch_trad and ch_trad != ch_simp:
                parts.append(f"  - {ch_simp}({ch_trad})")
            else:
                parts.append(f"  - {ch_simp}")
            parts.append(f"    - {ch_pin}")
            parts.append(f"    - {ch_eng}")
    elif components:
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

    # Etymology (structured with type, description, interpretation, simplification)
    if etymology and isinstance(etymology, dict):
        # Check for error state
        if "error" in etymology:
            parts.append(f"- **error:** {etymology['error']}")
        else:
            ety_type = etymology.get("type", "")
            ety_desc = etymology.get("description", "")
            ety_interp = etymology.get("interpretation", "")
            ety_simp = etymology.get("simplification", "")
            if ety_type or ety_desc or ety_interp or ety_simp:
                parts.append("- **etymology:**")
                if ety_type:
                    parts.append(f"  - **type:** {ety_type}")
                if ety_desc:
                    parts.append(f"  - **description:** {ety_desc}")
                if ety_interp:
                    parts.append(f"  - **interpretation:** {ety_interp}")
                if ety_simp:
                    parts.append(f"  - **simplification:** {ety_simp}")

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
    breadcrumbs: Optional[List[Tuple[str, str]]] = None,
    out_dir: Optional[Path] = None,
    parent_word: Optional[str] = None,
    errors: Optional[List[str]] = None,
) -> List[str]:
    """Recursively generate card sections for all component characters.

    Uses depth-first traversal in component list order.
    Returns list of error messages for any failed sub-components.

    Args:
        breadcrumbs: List of (simplified, traditional) tuples showing parent path.
    """
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

        # Fetch Wiktionary etymology for this component (simplified and traditional)
        wiki_ety = fetch_wiktionary_etymology(comp_simp, comp_trad, verbose=verbose)

        # Generate all content in single API call
        comp_etymology, sub_components, _, comp_examples, from_cache = generate_card_content(
            comp_simp, comp_trad, comp_pin, comp_eng,
            wiktionary_etymology=wiki_ety, model=model, verbose=verbose
        )

        # Check for error state and track
        if comp_etymology and comp_etymology.get("error"):
            error_msg = comp_etymology.get("error", "Unknown error")
            errors.append(f"{comp_simp}: {error_msg}")
            if out_dir and parent_word:
                add_subcomponent_error(out_dir, parent_word, comp_simp, error_msg)

        # Write complete cache entry only if newly generated (not from cache)
        if not from_cache:
            _write_complete_cache(
                comp_simp, comp_simp, comp_trad, comp_pin, comp_eng,
                etymology=comp_etymology, components=sub_components, examples=comp_examples,
                verbose=verbose,
            )

        # Current breadcrumbs for this component (include traditional)
        current_breadcrumbs = breadcrumbs + [(comp_simp, comp_trad)]

        # Write card for this component (as a sub-card)
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
            breadcrumbs=breadcrumbs,  # Show parent path, not including self
        )

        # Recursively process sub-components (depth-first)
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
    examples: Optional[List[Tuple[str, str, str]]] = None,
    model: Optional[str] = None,
    verbose: bool = False,
) -> Tuple[Path, List[str]]:
    """Write a Chinese flashcard markdown file.

    Always generates recursive component cards (for words with <5 characters).
    Returns (md_path, list_of_subcomponent_errors).
    """
    md_path = out_dir / f"{word}.md"
    parts: List[str] = []
    subcomponent_errors: List[str] = []

    # Check if main etymology has error
    if etymology and etymology.get("error"):
        subcomponent_errors.append(f"{simplified}: {etymology.get('error')}")

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

    # Generate recursive cards for components/characters
    cjk_chars = [ch for ch in simplified if is_cjk_char(ch)]
    visited: Set[str] = {simplified}

    # Initial breadcrumb is the main word (simplified, traditional)
    initial_breadcrumb = [(simplified, traditional)]

    if len(cjk_chars) == 1 and components:
        # Single character: recurse into components
        comp_errors = _generate_recursive_component_cards(
            parts, components, model, visited, depth=1, max_depth=5, verbose=verbose,
            breadcrumbs=initial_breadcrumb,
            out_dir=out_dir,
            parent_word=word,
            errors=subcomponent_errors,
        )
        subcomponent_errors = comp_errors
    elif len(cjk_chars) > 1 and characters:
        # Multi-character word: recurse into each character
        for ch_simp, ch_trad, ch_pin, ch_eng in characters:
            if ch_simp in visited:
                continue
            visited.add(ch_simp)

            # Fetch Wiktionary etymology for this character (simplified and traditional)
            ch_wiki_ety = fetch_wiktionary_etymology(ch_simp, ch_trad, verbose=verbose)

            # Generate all content in single API call
            ch_etymology, ch_components, _, ch_examples, from_cache = generate_card_content(
                ch_simp, ch_trad, ch_pin, ch_eng,
                wiktionary_etymology=ch_wiki_ety, model=model, verbose=verbose
            )

            # Check for error state and track
            if ch_etymology and ch_etymology.get("error"):
                error_msg = ch_etymology.get("error", "Unknown error")
                subcomponent_errors.append(f"{ch_simp}: {error_msg}")
                add_subcomponent_error(out_dir, word, ch_simp, error_msg)

            # Write complete cache entry only if newly generated (not from cache)
            if not from_cache:
                _write_complete_cache(
                    ch_simp, ch_simp, ch_trad, ch_pin, ch_eng,
                    etymology=ch_etymology, components=ch_components, examples=ch_examples,
                    verbose=verbose,
                )

            # Breadcrumbs for this character (include traditional)
            char_breadcrumbs = initial_breadcrumb + [(ch_simp, ch_trad)]

            # Write card for this character (as sub-card)
            _write_single_card(
                parts,
                simplified=ch_simp,
                traditional=ch_trad,
                pinyin=ch_pin,
                english=ch_eng,
                components=ch_components if ch_components else None,
                etymology=ch_etymology if ch_etymology else None,
                examples=ch_examples if ch_examples else None,
                is_subcard=True,
                breadcrumbs=initial_breadcrumb,  # Show parent (the word)
            )

            # Recursively process this character's components
            if ch_components:
                _generate_recursive_component_cards(
                    parts, ch_components, model, visited, depth=2, max_depth=5, verbose=verbose,
                    breadcrumbs=char_breadcrumbs,
                    out_dir=out_dir,
                    parent_word=word,
                    errors=subcomponent_errors,
                )

    # Add footer for main card (reverse side reference) after all recursive content
    # Format: ---, Chinese, Pinyin, ---, English
    if traditional and traditional != simplified:
        chinese_heading = f"{simplified}({traditional})"
    else:
        chinese_heading = simplified
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
        # Fetch Wiktionary etymology for this word (simplified and traditional)
        wiki_ety = fetch_wiktionary_etymology(simp or headword, trad or headword, verbose=verbose)

        # Generate all content in single API call (etymology, components/characters, examples)
        input_examples = phrase if phrase and phrase.strip() and phrase.strip().lower() != "none" else None
        etymology, components, characters, examples, from_cache = generate_card_content(
            simp, trad, pin, eng, input_examples=input_examples,
            wiktionary_etymology=wiki_ety, model=model, verbose=verbose
        )

        # Write complete cache entry for main headword only if newly generated
        if not from_cache:
            _write_complete_cache(
                simp or headword, simp or headword, trad or headword, pin, eng,
                etymology=etymology, components=components, character_breakdown=characters,
                examples=examples, verbose=verbose,
            )

        # Write card (handles recursive component generation internally)
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

        # Check for any errors (main card or subcomponents)
        if subcomponent_errors:
            error_msg = f"Subcomponent errors: {'; '.join(subcomponent_errors)}"
            mark_word_error(out_dir, file_base, error_msg)
            if verbose:
                print(f"[chinese] [ERROR] Card has subcomponent errors: {file_base}")
                for err in subcomponent_errors:
                    print(f"  - {err}")
            return 1, 1  # Card was created but with errors

        # Mark complete only if no errors
        mark_word_complete(out_dir, file_base)

        if verbose:
            print(f"[chinese] [ok] Card created: {file_base}")
        return 1, 1

    except Exception as e:
        # Mark as error with message
        mark_word_error(out_dir, file_base, str(e))
        if verbose:
            print(f"[chinese] [error] Failed to generate card for {file_base}: {e}")
        raise


def _clear_output_folder(out_dir: Path, verbose: bool = False) -> None:
    """Clear all contents from output folder."""
    import shutil
    if not out_dir.exists():
        return

    # Delete everything in the output folder
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


def process_chinese_folder(
    folder: Path,
    model: Optional[str] = None,
    verbose: bool = False,
    chunk_range: Optional[Tuple[int, int]] = None,
    workers: Optional[int] = None,
) -> Tuple[int, int]:
    """Process a folder of Chinese vocabulary words.

    Args:
        folder: Output folder for generated cards
        model: OpenAI model name
        verbose: Enable verbose logging
        chunk_range: If specified, process only words from those chunks
        workers: Number of parallel workers (default: DEFAULT_PARALLEL_WORKERS)

    Returns (total_words, cards_created) tuple.
    """
    out_dir = folder

    # Get input-parsed directory (sibling to output folder)
    input_parsed_dir = _get_input_parsed_dir(out_dir)

    # Clear output folder (remove all generated files, rely on cache)
    _clear_output_folder(out_dir, verbose=verbose)

    # Read input from input-parsed directory
    parsed_path = input_parsed_dir / "-input.parsed.csv"
    if not parsed_path.exists():
        # Try chunk CSVs from input-parsed
        all_rows = _read_all_chunk_csvs(input_parsed_dir)
    else:
        rows = read_parsed_input(parsed_path)
        # Skip sub-words (relation field not empty)
        # Compute chunk_num from index (50 entries per chunk)
        all_rows = [(idx, ((idx - 1) // 50) + 1, s, t, p, e, ph, r) for idx, (s, t, p, e, ph, r) in enumerate(rows, start=1) if not r.strip()]

    if not all_rows:
        if verbose:
            print(f"[chinese] [skip] No parsed input in {input_parsed_dir}")
        return 0, 0

    # Initialize manifest (fresh each time, rely on cache for resumption)
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

        md_files = [p for p in sorted(out_dir.glob("*.md")) if not p.name.startswith("-output") and not p.name.startswith("-")]
        parts: List[str] = []
        for p in md_files:
            try:
                parts.append(p.read_text(encoding="utf-8", errors="ignore").rstrip())
            except Exception:
                if verbose:
                    print(f"[chinese] [warn] failed reading {p.name} for {output_name}")
        # Join cards with %%% divider
        content = f"\n{CARD_DIVIDER}\n".join(parts) + ("\n" if parts else "")
        output_md.write_text(content, encoding="utf-8")
        if verbose:
            print(f"[chinese] [ok] Wrote {output_name} ({len(content)} bytes) with {len(md_files)} files")
    except Exception as e:
        if verbose:
            print(f"[chinese] [warn] failed to write output: {e}")
