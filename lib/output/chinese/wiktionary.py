"""Wiktionary etymology fetching for Chinese characters."""

import re
import time

import requests
from bs4 import BeautifulSoup

from lib.output.chinese.cache import CHINESE_CACHE_DIR

# Module-level session for connection reuse
_session = requests.Session()
_session.headers.update({
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
})


def _fetch_with_retry(url: str, max_retries: int = 3, base_delay: float = 1.0, verbose: bool = False):
    """Fetch URL with exponential backoff retry on errors and non-200 responses.

    Returns response object or None if all retries failed.
    Does NOT retry 404s (page doesn't exist - permanent error).
    """
    for attempt in range(max_retries):
        try:
            resp = _session.get(url, timeout=20)

            # Success
            if resp.status_code == 200:
                return resp

            # 404 is permanent - don't retry
            if resp.status_code == 404:
                return resp

            # Retry on other non-200 status codes
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                if verbose:
                    print(f"[wiktionary] [retry] status {resp.status_code}, retrying in {delay}s (attempt {attempt + 1}/{max_retries})")
                time.sleep(delay)
                continue

            # Last attempt failed
            return resp

        except Exception as e:
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                if verbose:
                    print(f"[wiktionary] [error] {e}, retrying in {delay}s (attempt {attempt + 1}/{max_retries})")
                time.sleep(delay)
                continue
            if verbose:
                print(f"[wiktionary] [error] {e}")
            return None

    return None


def _extract_see_reference(html: str) -> tuple[str, str, bool]:
    """Extract 'see X' reference if the page redirects to another character.

    Looks for patterns like:
    - "For pronunciation and definitions of 䌓 – see 繁" (hard redirect)
      followed by "(This character is a variant form of 繁)."
    - "See also: 麥" (soft redirect)

    Returns (referenced_character, relationship, is_hard_redirect) where:
    - referenced_character: the character to look up, or empty string if not found
    - relationship: e.g. "variant form of 繁", "traditional form of 简", or empty string
    - is_hard_redirect: True if this is a "For X see Y" style redirect (use Y's etymology for X)
    """
    soup = BeautifulSoup(html, "html.parser")

    # CJK character pattern (only match actual Chinese characters, not English words)
    cjk_char = r'[\u4e00-\u9fff\u3400-\u4dbf\U00020000-\U0002a6df]'

    # Look for the "see also" pattern in the page
    for tag in soup.find_all(["p", "div", "span", "dd", "li"]):
        text = tag.get_text()
        # Pattern 1: "For pronunciation and definitions of X – see Y" (hard redirect)
        # Exact Wiktionary format: "For pronunciation and definitions of 䌓 – see 繁"
        # This means X is a variant of Y, use Y's info for X
        match = re.search(rf'For pronunciation and definitions of {cjk_char}+\s*[–—-]\s*see\s+({cjk_char}+)', text)
        if match:
            ref_char = match.group(1).strip()
            # Look for relationship description like "(This character is a variant form of 繁)"
            # or "(This character is the traditional form of 简)"
            relationship = ""
            rel_match = re.search(
                rf'\(This character is (?:a |the )?(.+? form of {cjk_char}+)\)',
                text,
                re.IGNORECASE
            )
            if rel_match:
                relationship = rel_match.group(1).strip().rstrip('.')
            return (ref_char, relationship, True)
        # Pattern 2: "See also: X" (soft redirect - just additional info, only CJK chars)
        match = re.search(rf'See\s+also:\s*({cjk_char}+)', text)
        if match:
            return (match.group(1).strip(), "", False)

    return ("", "", False)


def _extract_definitions_from_html(html: str, max_defs: int = 3) -> str:
    """Extract the first N definitions from the Chinese section.

    Returns definitions as a numbered list, or empty string if not found.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Find main content
    content = soup.find("div", {"id": "mw-content-text"})
    if not content:
        return ""

    # Find Chinese section by looking for h2 with "Chinese" text
    chinese_section_start = None
    chinese_section_end = None

    for h2 in content.find_all("h2"):
        heading_text = h2.get_text().lower()
        if "chinese" in heading_text:
            chinese_section_start = h2
        elif chinese_section_start and heading_text and not heading_text.startswith("chinese"):
            # Found next language section
            chinese_section_end = h2
            break

    if not chinese_section_start:
        return ""

    # Find all OL tags between Chinese heading and next language heading
    definitions = []

    # Get all elements after Chinese heading
    for ol in content.find_all("ol"):
        # Check if this OL is after Chinese heading and before next section
        if chinese_section_start:
            # Check position relative to Chinese heading
            chinese_pos = str(content).find(str(chinese_section_start))
            ol_pos = str(content).find(str(ol))

            if ol_pos <= chinese_pos:
                continue  # OL is before Chinese section

            if chinese_section_end:
                end_pos = str(content).find(str(chinese_section_end))
                if ol_pos >= end_pos:
                    continue  # OL is after Chinese section

        # Extract definitions from this OL
        for li in ol.find_all("li", recursive=False):
            text = li.get_text(separator=" ", strip=True)
            if text and len(text) > 5:
                # Clean up
                text = re.sub(r'\[edit\]', '', text, flags=re.IGNORECASE)
                text = re.sub(r'\s+', ' ', text).strip()
                # Skip Kangxi radical entries and other non-definitions
                if text and not text.startswith("Category:") and not text.startswith("Kangxi"):
                    definitions.append(text)
                    if len(definitions) >= max_defs:
                        break
        if len(definitions) >= max_defs:
            break

    if not definitions:
        return ""

    # Format as numbered list
    result = []
    for i, defn in enumerate(definitions[:max_defs], 1):
        result.append(f"{i}. {defn}")

    return "\n".join(result)


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
        # Extract from paragraph tags
        if sibling.name == "p":
            text = sibling.get_text(separator=" ", strip=True)
            if text and len(text) > 5:
                # Clean up
                text = re.sub(r'\[edit\]', '', text, flags=re.IGNORECASE)
                text = re.sub(r'\s+', ' ', text).strip()
                if text:
                    section_text.append(text)
        # Also extract from list items (bullet points with detailed explanations)
        elif sibling.name == "ul":
            for li in sibling.find_all("li", recursive=False):
                text = li.get_text(separator=" ", strip=True)
                if text and len(text) > 5:
                    text = re.sub(r'\[edit\]', '', text, flags=re.IGNORECASE)
                    text = re.sub(r'\s+', ' ', text).strip()
                    if text:
                        section_text.append(f"• {text}")

    return "\n".join(section_text)


def fetch_wiktionary_etymology(simplified: str, traditional: str = "", verbose: bool = False) -> str:
    """Fetch and extract ONLY etymology/glyph origin from Wiktionary.

    Fetches BOTH simplified and traditional forms if they differ.
    Saves to cache directory as {word}.etymology.txt alongside the JSON cache.
    Returns the combined etymology text, or empty string if not found.
    """
    CHINESE_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # Determine which words to fetch
    words_to_fetch = [simplified]
    if traditional and traditional != simplified:
        words_to_fetch.append(traditional)

    # Build cache key from all words
    cache_key = simplified if not traditional or traditional == simplified else f"{simplified}_{traditional}"
    cache_path = CHINESE_CACHE_DIR / f"{cache_key}.etymology.txt"

    # Check cache first - if file exists, respect it (even if empty)
    if cache_path.exists():
        try:
            content = cache_path.read_text(encoding="utf-8").strip()
            if verbose:
                print(f"[wiktionary] [cache] {cache_key}")
            return content  # Return cached content (may be empty string)
        except Exception:
            pass

    all_etymology_parts = []
    all_404 = True  # Track if all failures were 404s (page doesn't exist)
    had_success = False  # Track if any page was fetched successfully

    for word in words_to_fetch:
        # Fetch from Wiktionary with retry and backoff
        url = f"https://en.wiktionary.org/wiki/{requests.utils.requote_uri(word)}"
        resp = _fetch_with_retry(url, verbose=verbose)

        if resp is None or resp.status_code != 200:
            if resp is not None and resp.status_code == 404:
                if verbose:
                    print(f"[wiktionary] [404] {word}: page not found")
            else:
                all_404 = False  # Non-404 error, don't cache empty
                if verbose and resp is not None:
                    print(f"[wiktionary] [skip] {word}: status {resp.status_code}")
            continue

        all_404 = False  # Got a successful response
        had_success = True  # At least one page was fetched

        if verbose:
            print(f"[wiktionary] [fetch] {word} ({resp.elapsed.total_seconds():.1f}s)")

        # Check for "See also: X" or "For X see Y" reference
        see_ref, relationship, is_hard_redirect = _extract_see_reference(resp.text)
        if see_ref and see_ref != word and see_ref not in words_to_fetch:
            # Skip unrenderable characters (surrogate pairs, rare CJK extensions)
            if len(see_ref) > 1 or ord(see_ref[0]) > 0xFFFF:
                if verbose:
                    print(f"[wiktionary] [skip-ref] {word} → {see_ref} (unrenderable character)")
            else:
                words_to_fetch.append(see_ref)
                if verbose:
                    print(f"[wiktionary] [see-also] {word} → will also fetch {see_ref}")

        # Extract etymology from this page
        etymology = _extract_etymology_from_html(resp.text)

        # For hard redirects with no etymology on this page, just add relationship and continue
        if is_hard_redirect and not etymology and relationship:
            all_etymology_parts.append(f"[{word}]\n{relationship}")
            continue

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

    # Save to cache if:
    # 1. We got actual content, OR
    # 2. All pages were 404s (pages don't exist - cache empty to avoid retrying), OR
    # 3. Pages exist but have no extractable etymology (cache empty to avoid retrying)
    if result:
        cache_path.write_text(result, encoding="utf-8")
        if verbose:
            print(f"[wiktionary] [save] {cache_key}")
    elif all_404:
        # All pages were 404 - save empty file to avoid retrying
        cache_path.write_text("", encoding="utf-8")
        if verbose:
            print(f"[wiktionary] [save-404] {cache_key} (pages not found)")
    elif had_success:
        # Pages exist but no extractable etymology - save empty to avoid retrying
        cache_path.write_text("", encoding="utf-8")
        if verbose:
            print(f"[wiktionary] [save-empty] {cache_key} (no extractable etymology)")
    else:
        if verbose:
            print(f"[wiktionary] [no-cache] {cache_key} (transient error)")

    return result
