"""Wiktionary etymology fetching for Chinese characters."""

import re
import time

import requests
from bs4 import BeautifulSoup

from lib.output.chinese.cache import CHINESE_CACHE_DIR

# Module-level session for connection reuse
_session = requests.Session()
_session.headers.update({"User-Agent": "flashcards-script/1.0"})


def _extract_see_reference(html: str) -> str:
    """Extract 'see X' reference if the page redirects to another character.

    Looks for patterns like "See also: 麥" or "For pronunciation and definitions of 麦 – see 麥"
    Returns the referenced character, or empty string if not found.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Look for the "see also" pattern in the page
    for tag in soup.find_all(["p", "div", "span", "dd", "li"]):
        text = tag.get_text()
        # Pattern 1: "See also: X"
        match = re.search(r'See\s+also:\s*(\S+)', text)
        if match:
            return match.group(1).strip()
        # Pattern 2: "For ... of X – see Y" or "For ... of X — see Y"
        match = re.search(r'For\s+.*?\s+of\s+\S+\s*[–—-]\s*see\s+(\S+)', text)
        if match:
            return match.group(1).strip()

    return ""


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

    for word in words_to_fetch:
        # Fetch from Wiktionary with rate limiting backoff
        url = f"https://en.wiktionary.org/wiki/{requests.utils.requote_uri(word)}"
        max_retries = 3
        base_delay = 1.0
        resp = None

        for attempt in range(max_retries):
            try:
                resp = _session.get(url, timeout=20)

                # Handle rate limiting (429) with exponential backoff
                if resp.status_code == 429:
                    delay = base_delay * (2 ** attempt)
                    print(f"[wiktionary] [rate-limit] {word}: retrying in {delay}s (attempt {attempt + 1}/{max_retries})")
                    time.sleep(delay)
                    continue

                if resp.status_code != 200:
                    if verbose:
                        print(f"[wiktionary] [skip] {word}: status {resp.status_code}")
                    break  # Don't retry non-429 errors

                # Success - break out of retry loop
                break

            except Exception as e:
                if verbose:
                    print(f"[wiktionary] [error] {word}: {e}")
                if attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt)
                    time.sleep(delay)
                    continue
                break
        else:
            # All retries exhausted
            if verbose:
                print(f"[wiktionary] [error] {word}: max retries exceeded")
            continue

        # Check if we got a successful response
        if resp is None or resp.status_code != 200:
            continue

        fetch_elapsed = time.time() - (resp.elapsed.total_seconds() if hasattr(resp, 'elapsed') else 0)
        if verbose:
            print(f"[wiktionary] [fetch] {word} ({resp.elapsed.total_seconds():.1f}s)")

        # Check for "See also: X" reference and fetch that entry too
        see_ref = _extract_see_reference(resp.text)
        if see_ref and see_ref != word and see_ref not in words_to_fetch:
            words_to_fetch.append(see_ref)
            if verbose:
                print(f"[wiktionary] [see-also] {word} → will also fetch {see_ref}")

        # Extract etymology from this page
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

    # Always save to cache (even if empty) to prevent re-fetching
    cache_path.write_text(result, encoding="utf-8")
    if verbose:
        if result:
            print(f"[wiktionary] [save] {cache_key}")
        else:
            print(f"[wiktionary] [save-empty] {cache_key}")

    return result
