#!/usr/bin/env python3
"""
One-off script to retroactively strip HTML tags from all existing .input.html files.

This reduces token costs by converting HTML to plain text while preserving content structure.
"""

import sys
from pathlib import Path

# Add parent directory to path to import from project
sys.path.insert(0, str(Path(__file__).parent.parent))

from bs4 import BeautifulSoup


def sanitize_html_to_text(html: str) -> str:
    """Aggressively strip HTML and compress to minimal text, removing most whitespace."""
    soup = BeautifulSoup(html, "html.parser")
    
    # Try to extract just the main content div (for Wiktionary pages)
    main_content = soup.find(id="mw-content-text")
    if main_content:
        soup = main_content
    
    # Remove unwanted sections entirely (but NOT meta, as Wiktionary content may be inside it)
    for tag in soup(["script", "style", "noscript", "footer", "nav", "header", "link", 
                     "form", "button", "input", "select"]):
        tag.decompose()
    
    # Remove specific navigation/UI elements by ID
    for element_id in ["mw-navigation", "mw-head", "mw-panel", "footer", "catlinks", 
                      "siteSub", "contentSub", "jump-to-nav"]:
        element = soup.find(id=element_id)
        if element:
            element.decompose()
    
    # Remove very large tables (dialect/pronunciation tables are huge)
    for tag in soup.find_all(["table"]):
        try:
            text_len = len(tag.get_text(" ", strip=True))
        except Exception:
            text_len = 0
        # Be more aggressive - most tables are pronunciation data we don't need in detail
        if text_len > 2000:
            tag.decompose()
    
    # Aggressively limit lists to first 15 items
    for tag in soup.find_all(["ul", "ol"]):
        try:
            items = tag.find_all("li", recursive=False)
        except Exception:
            items = []
        if len(items) > 15:
            for li in items[15:]:
                li.decompose()
    
    # Extract text with spaces as separator (not newlines)
    text = soup.get_text(separator=" ", strip=True)
    
    # Remove common redundant phrases
    redundant_phrases = [
        "Jump to content",
        "From Wiktionary, the free dictionary",
        "edit",
        "[edit]",
        "Toggle the table of contents",
        "Personal tools",
        "Navigation",
        "Contribute",
        "Print/export",
        "In other projects",
        "Languages",
        "Tools",
        "Appearance",
        "See also:",
        "Further reading:",
        "References:",
        "Retrieved from",
        "Categories:",
        "Hidden categories:",
        "See images of",
        "Wikipedia has an article on:",
        "Wikipedia has articles on:",
        "English Wikipedia has an article on:",
    ]
    for phrase in redundant_phrases:
        text = text.replace(phrase, "")
    
    # Collapse multiple spaces to single space
    import re
    text = re.sub(r'\s+', ' ', text)
    
    # Remove all [ ] brackets (often navigation/edit markers)
    text = re.sub(r'\[\s*\]', '', text)
    text = re.sub(r'\[edit\]', '', text)
    
    # Remove Unicode values and CJK identifiers
    text = re.sub(r'U\+[0-9A-F]{4,5}', '', text)
    text = re.sub(r'CJK Unified Ideographs?-?[0-9A-F]*', '', text, flags=re.IGNORECASE)
    text = re.sub(r'&#\d+;?', '', text)
    
    # Remove navigation arrows and references
    text = re.sub(r'[←→]\s*[^\s]*\s*\[.*?\]', '', text)
    text = re.sub(r'[←→]', '', text)
    
    # Remove IPA and pronunciation notation
    text = re.sub(r'IPA\s*\([^)]*\)\s*:\s*/[^/]+/', '', text)
    text = re.sub(r'Sinological\s*IPA[^:]*:[^/]*/[^/]+/', '', text)
    text = re.sub(r'Sinological', '', text)  # Remove all remaining "Sinological"
    
    # Remove excessive romanization system names
    text = re.sub(r'(Baxter|Zhengzhang|Palladius|Wade–Giles|Gwoyeu Romatzyh|Tongyong Pinyin|Hanyu Pinyin|Zhuyin|Jyutping|Cantonese Pinyin|Guangdong Romanization|Hakka Romanization System|Pouseng Ping|Báⁿ-uā-ci̍|Pe̍h-ōe-jī|Tâi-lô|Phofsit Daibuun|Kienning Colloquial Romanized|Bàng-uâ-cê|Leizhou Pinyin|Wugniu|MiniDict|Wiktionary Romanisation)[^:]*:\s*[^\s]*', '', text)
    
    # Remove Reading # markers
    text = re.sub(r'Reading\s*#?\s*\d+/\d+', '', text)
    
    # Remove technical metadata phrases
    text = re.sub(r'(Rime Character|Initial \( 聲 \)|Final \( 韻 \)|Tone \( 調 \)|Openness \( 開合 \)|Division \( 等 \)|Fanqie|Reconstructions|Kangxi radical|cangjie input|four-corner|composition)[^:]*:', '', text)
    
    # Remove template/metadata warnings
    text = re.sub(r'(The template.*?does not use the parameter|Please see Module:checkparams|This term needs a translation|Please help out and add|then remove the text)', '', text)
    
    # Remove Wikipedia references and links
    text = re.sub(r'Wikipedia\s+\w+', '', text)
    text = re.sub(r'(See|From|Compare|Particularly):?\s+"[^"]*"', '', text)
    
    # Remove "Notes for Old Chinese notations" and similar
    text = re.sub(r'Notes for Old [^:]*:.*?boundary\.', '', text, flags=re.DOTALL)
    
    # Remove repeated characters/patterns (common in navigation)
    text = re.sub(r'(\.{3,})', '...', text)
    
    # Remove category listings at end
    text = re.sub(r'(Categories|Hidden categories):.*$', '', text)
    
    # Remove dialect/variety tables (these are very verbose)
    text = re.sub(r'Dialectal (data|synonyms) Variety Location.*?(?=\n[A-Z]|\Z)', '', text, flags=re.DOTALL)
    
    # Remove extensive pronunciation system details
    text = re.sub(r'\(Standard\s+Chinese[^\)]*\)\s*\+', '', text)
    text = re.sub(r'(Mandarin|Cantonese|Hakka|Min|Wu|Xiang|Gan)\s*\([^)]{50,}\)', '', text)
    
    # Remove phonetic notations in slashes and brackets  
    text = re.sub(r'/[^/]{10,}/', '', text)  # Long IPA between slashes
    text = re.sub(r'\([^)]*?ː[^)]*?\)', '', text)  # IPA with length markers
    
    # Remove reference citations like "[ 1 ]", "[ 2 ]", etc.
    text = re.sub(r'\[\s*\d+\s*\]', '', text)
    
    # Remove "ion" typos (likely "edition")
    text = text.replace(' ion ', ' edition ')
    
    # Remove excessive parenthetical content that's often metadata
    text = re.sub(r'\([^)]{100,}\)', '', text)
    
    # Collapse multiple spaces (but preserve section markers first)
    text = re.sub(r'\s+', ' ', text)
    
    # NOW add strategic newlines for major sections (after whitespace collapse)
    for marker in ["Etymology", "Pronunciation", "Definitions", "Derived terms", 
                  "Compounds", "See also", "References", "Further reading",
                  "Translingual", "Chinese", "Japanese", "Korean", "Vietnamese"]:
        text = text.replace(f" {marker} ", f"\n{marker}: ")
        text = text.replace(f" {marker}:", f"\n{marker}:")
    
    # Truncate if still too long
    if len(text) > 20_000:
        text = text[:20_000]
    
    return text.strip()


def process_html_file(path: Path, verbose: bool = True, create_parsed: bool = False) -> tuple[int, int]:
    """Process a single HTML file and return (original_size, new_size).
    
    Args:
        path: Path to the .input.html file
        verbose: Whether to print progress
        create_parsed: If True, create .input.html.parsed instead of overwriting
    """
    try:
        original_html = path.read_text(encoding="utf-8", errors="ignore")
        original_size = len(original_html)
        
        # Split by word headers if present
        parts = []
        if "<!-- word:" in original_html:
            # Process each word section separately
            sections = original_html.split("<!-- word:")
            for i, section in enumerate(sections):
                if not section.strip():
                    continue
                if i == 0:
                    # First section before any word marker
                    parts.append(section)
                else:
                    # Extract word and HTML
                    lines = section.split("\n", 2)
                    if len(lines) >= 2:
                        word_line = lines[0].strip().rstrip("-->").strip()
                        rest = "\n".join(lines[1:]) if len(lines) > 1 else ""
                        
                        # Preserve the word header and h1
                        parts.append(f"<!-- word: {word_line} -->\n")
                        if rest.strip():
                            # Extract just the h1 if present, then sanitize the rest
                            if "<h1>" in rest:
                                h1_start = rest.find("<h1>")
                                h1_end = rest.find("</h1>", h1_start)
                                if h1_end > h1_start:
                                    h1_content = rest[h1_start+4:h1_end]
                                    parts.append(f"{h1_content}\n\n")
                                    rest = rest[h1_end+5:]
                            
                            # Sanitize the rest
                            clean_text = sanitize_html_to_text(rest)
                            parts.append(clean_text)
            
            new_content = "\n\n".join(p.strip() for p in parts if p.strip())
        else:
            # No word markers, just sanitize entire content
            new_content = sanitize_html_to_text(original_html)
        
        new_size = len(new_content)
        
        # Determine output path
        if create_parsed:
            # Create .input.html.parsed file (keep original)
            output_path = path.with_suffix(path.suffix + '.parsed')
        else:
            # Overwrite original
            output_path = path
        
        # Write to output file
        output_path.write_text(new_content, encoding="utf-8")
        
        if verbose:
            if create_parsed:
                print(f"✓ {path.name} → {output_path.name}: {new_size:,} bytes")
            else:
                reduction_pct = ((original_size - new_size) / original_size * 100) if original_size > 0 else 0
                print(f"✓ {path.name}: {original_size:,} → {new_size:,} bytes ({reduction_pct:.1f}% reduction)")
        
        return original_size, new_size
    
    except Exception as e:
        print(f"✗ {path.name}: Error - {e}", file=sys.stderr)
        return 0, 0


def main():
    """Find and process all .input.html files in the output directory."""
    import argparse
    parser = argparse.ArgumentParser(description="Strip and compress HTML files for flashcard generation")
    parser.add_argument("--create-parsed", action="store_true", 
                       help="Create .input.html.parsed files instead of overwriting originals")
    args = parser.parse_args()
    
    # Get project root
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    output_dir = project_root / "output"
    
    if not output_dir.exists():
        print(f"Error: Output directory not found: {output_dir}", file=sys.stderr)
        return 1
    
    # Find all .input.html files
    html_files = list(output_dir.rglob("*.input.html"))
    
    if not html_files:
        print("No .input.html files found.")
        return 0
    
    if args.create_parsed:
        print(f"Found {len(html_files)} HTML files. Creating .parsed versions...\n")
    else:
        print(f"Found {len(html_files)} HTML files to process.\n")
    
    total_original = 0
    total_new = 0
    processed = 0
    
    for html_file in sorted(html_files):
        orig, new = process_html_file(html_file, verbose=True, create_parsed=args.create_parsed)
        total_original += orig
        total_new += new
        if orig > 0:
            processed += 1
    
    # Summary
    if processed > 0:
        total_reduction_pct = ((total_original - total_new) / total_original * 100) if total_original > 0 else 0
        print(f"\n{'='*70}")
        print(f"✅ Processing Complete!")
        print(f"{'='*70}")
        print(f"Files processed: {processed}")
        print(f"Total original size: {total_original:,} bytes ({total_original/1024/1024:.2f} MB)")
        print(f"Total new size: {total_new:,} bytes ({total_new/1024/1024:.2f} MB)")
        print(f"Total reduction: {total_original - total_new:,} bytes ({total_reduction_pct:.1f}%)")
        print(f"{'='*70}\n")
        
        # Estimate token savings (rough approximation: 1 token ≈ 4 bytes)
        token_savings = (total_original - total_new) / 4
        cost_savings_per_run = token_savings / 1_000_000 * 0.15  # $0.15 per 1M input tokens
        print(f"💰 Estimated savings per generation run:")
        print(f"   • ~{token_savings:,.0f} fewer input tokens")
        print(f"   • ~${cost_savings_per_run:.2f} saved on input costs")
        print(f"{'='*70}\n")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

