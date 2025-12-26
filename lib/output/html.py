"""HTML fetching and parsing utilities for Wiktionary."""

import re
from pathlib import Path
from typing import Tuple

import requests
from bs4 import BeautifulSoup  # type: ignore


def wiktionary_url_for_word(word: str) -> str:
    """Get the English Wiktionary URL for a Chinese word."""
    return f"https://en.wiktionary.org/wiki/{requests.utils.requote_uri(word)}"


def fetch_wiktionary_html_status(word: str, timeout: float = 20.0) -> Tuple[str, int]:
    """Fetch HTML from Wiktionary and return (html_content, status_code)."""
    url = wiktionary_url_for_word(word)
    try:
        resp = requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": "flashcards-script/1.0 (+https://example.local)"},
        )
        status = resp.status_code
        text = resp.text if resp.text is not None else ""
        return text, status
    except Exception:
        return "", 0


def section_header(word: str) -> str:
    """Create an HTML section header for a word."""
    return f"<!-- word: {word} -->\n<h1>{word}</h1>\n"


def _extract_sections_from_soup(soup, word_label: str = "") -> list:
    """Extract sections from a BeautifulSoup object for a single character page."""
    sections = []
    prefix = f"[{word_label}] " if word_label else ""
    
    # Try to find main content
    main_content = soup.find(id="mw-content-text")
    if main_content:
        soup = main_content
    
    # Extract character composition info from headword-line
    headword = soup.find("span", class_="headword-line")
    if headword:
        text = headword.get_text(separator=" ", strip=True)
        text = re.sub(r'\s+', ' ', text)
        if text and len(text) > 3:
            sections.append(f"{prefix}Character info: {text}\n")
    
    # Extract "see Traditional" tables (zh-see class) - common for simplified characters
    zh_see_tables = soup.find_all("table", class_=lambda x: x and "zh-see" in x if x else False)
    for table in zh_see_tables:
        text = table.get_text(separator=" ", strip=True)
        text = re.sub(r'\s+', ' ', text)
        if text and len(text) > 10:
            sections.append(f"{prefix}Definition reference: {text}\n")
    
    # Helper to find section by heading text (handles mw-heading wrapper divs)
    def find_section_content(heading_texts, section_name):
        """Find content after a heading. heading_texts is a list of possible heading texts."""
        content = []
        
        for heading_text in heading_texts:
            # Try finding heading directly
            heading = soup.find(lambda tag: tag.name in ["h2", "h3", "h4", "h5"] 
                               and heading_text.lower() in tag.get_text().lower())
            if not heading:
                # Try finding in mw-heading div
                heading_div = soup.find("div", class_=lambda x: x and "mw-heading" in x if x else False,
                                       string=lambda s: s and heading_text.lower() in s.lower() if s else False)
                if heading_div:
                    heading = heading_div.find(["h2", "h3", "h4", "h5"])
            
            if not heading:
                continue
            
            # Get the parent container (might be mw-heading div or the heading itself)
            container = heading.parent if heading.parent.name == "div" else heading
            
            # Collect siblings until next heading
            for sibling in container.find_next_siblings():
                # Stop at next heading
                if sibling.name in ["h2", "h3", "h4", "h5"]:
                    break
                if sibling.find(["h2", "h3", "h4", "h5"]):
                    # Check if it's a major section break
                    inner_h = sibling.find(["h2", "h3"])
                    if inner_h:
                        break
                
                # Skip navigation/edit elements
                if sibling.get("class") and any(c in str(sibling.get("class")) for c in ["mw-heading", "navbox", "catlinks"]):
                    continue
                
                # Extract text
                text = sibling.get_text(separator=" ", strip=True)
                # Skip empty, edit links, and very short content
                if text and text not in ["[edit]", "edit"] and len(text) > 3:
                    # Clean up
                    text = re.sub(r'\[edit\]', '', text)
                    text = re.sub(r'\s+', ' ', text).strip()
                    if text:
                        content.append(text)
            
            if content:
                break
        
        if content:
            return f"{prefix}{section_name}:\n" + "\n".join(content) + "\n"
        return None
    
    # Extract Glyph origin
    glyph = find_section_content(["Glyph origin", "glyph origin"], "Glyph origin")
    if glyph:
        sections.append(glyph)
    
    # Extract Etymology
    etym = find_section_content(["Etymology"], "Etymology")
    if etym:
        sections.append(etym)
    
    # Extract Definitions (multiple possible headings)
    defs = find_section_content(["Definitions", "Noun", "Verb", "Adjective", "Adverb"], "Definitions")
    if defs:
        sections.append(defs)
    
    # Extract Pronunciation
    pron = find_section_content(["Pronunciation"], "Pronunciation")
    if pron:
        sections.append(pron)
    
    # Extract Derived terms / Compounds
    derived = find_section_content(["Derived terms", "Compounds", "Derived characters"], "Derived terms")
    if derived:
        sections.append(derived)
    
    # If we got nothing useful, try a broader extraction
    if not sections or (len(sections) == 1 and "Character info" in sections[0]):
        # Look for any Chinese section content
        chinese_section = soup.find("h2", id="Chinese")
        if chinese_section:
            container = chinese_section.parent if chinese_section.parent.name == "div" else chinese_section
            content_parts = []
            for sibling in container.find_next_siblings():
                if sibling.name == "h2" or (sibling.find("h2") and sibling.find("h2").get("id") != "Chinese"):
                    break
                text = sibling.get_text(separator=" ", strip=True)
                if text and len(text) > 10 and "[edit]" not in text:
                    text = re.sub(r'\s+', ' ', text).strip()
                    content_parts.append(text)
            if content_parts:
                sections.append(f"{prefix}Chinese content:\n" + "\n".join(content_parts[:10]) + "\n")
    
    return sections


def sanitize_html(html: str) -> str:
    """Extract specific sections from Wiktionary HTML.
    
    Handles modern Wiktionary HTML structure including:
    - mw-heading divs wrapping headings
    - zh-see tables for simplified->traditional redirects
    - Nested content structures
    - Multiple character pages combined with <!-- word: X --> markers
    """
    all_sections = []
    
    # Check if this is a combined HTML with multiple word sections
    word_marker_pattern = re.compile(r'<!-- word: (.+?) -->')
    markers = list(word_marker_pattern.finditer(html))
    
    if len(markers) > 1:
        # Multiple word sections - parse each separately
        for i, match in enumerate(markers):
            word_label = match.group(1)
            start_pos = match.end()
            # End at next marker or end of string
            end_pos = markers[i + 1].start() if i + 1 < len(markers) else len(html)
            section_html = html[start_pos:end_pos]
            
            soup = BeautifulSoup(section_html, "html.parser")
            sections = _extract_sections_from_soup(soup, word_label)
            all_sections.extend(sections)
    else:
        # Single page or no markers - parse as one
        soup = BeautifulSoup(html, "html.parser")
        all_sections = _extract_sections_from_soup(soup, "")
    
    # Combine sections
    result = "\n\n".join(all_sections)
    
    # Final cleanup
    lines = result.split('\n')
    cleaned_lines = []
    for line in lines:
        line = re.sub(r'\s+', ' ', line.strip())
        # Remove CSS that leaked through
        if not line.startswith(".mw-parser-output"):
            cleaned_lines.append(line)
    result = '\n'.join(cleaned_lines)
    
    # Truncate if too long
    if len(result) > 20_000:
        result = result[:20_000]
    
    return result.strip() if result.strip() else "No content extracted"


def save_html_with_parsed(html_path: Path, html_content: str, verbose: bool = False) -> None:
    """Save both original HTML and parsed version."""
    # Save original HTML
    html_path.write_text(html_content, encoding="utf-8")
    
    # Save parsed version
    parsed_path = html_path.with_suffix(html_path.suffix + '.parsed')
    parsed_content = sanitize_html(html_content)
    parsed_path.write_text(parsed_content, encoding="utf-8")
    
    if verbose:
        print(f"[file] Created HTML: {html_path.name} ({len(html_content):,} bytes)")
        print(f"[file] Created parsed: {parsed_path.name} ({len(parsed_content):,} bytes)")


def load_html_for_api(html_path: Path) -> str:
    """Load HTML for API call, preferring parsed version."""
    parsed_path = html_path.with_suffix(html_path.suffix + '.parsed')
    
    if parsed_path.exists():
        return parsed_path.read_text(encoding="utf-8", errors="ignore")
    elif html_path.exists():
        return sanitize_html(html_path.read_text(encoding="utf-8", errors="ignore"))
    else:
        return ""

