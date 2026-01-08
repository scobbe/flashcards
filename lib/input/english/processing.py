"""English vocabulary input parsing.

Simple input parsing for English mode:
- Reads raw text file with one word/phrase per line
- Skips comments (lines starting with #) and blank lines
- Sanitizes input (removes bullets, pronunciation guides, etc.)
- Writes -input.parsed.csv with one word per line
"""

import re
from pathlib import Path
from typing import List

from lib.common import init_input_manifest, mark_chunk_complete, is_chunk_complete


def sanitize_english_word(word: str) -> str:
    """Sanitize an English word/phrase by removing noise.

    Removes:
    - Leading bullet markers (*, -, •, etc.)
    - Pronunciation guides in parentheses with quotes: ("pro-NUN-see-ay-shun")
    - Leading/trailing quotes and whitespace
    - Numbered prefixes like "1." or "1)"

    Args:
        word: Raw word/phrase

    Returns:
        Sanitized word/phrase
    """
    # Strip whitespace
    word = word.strip()

    # Remove leading bullet markers
    word = re.sub(r'^[\*\-\•\◦\▪\►\→\·]+\s*', '', word)

    # Remove numbered prefixes like "1." or "1)" or "1:"
    word = re.sub(r'^\d+[\.\)\:]\s*', '', word)

    # Remove pronunciation guides: parentheticals containing quoted text
    # e.g., ("Plah-tee-uh") or ('pro-nun-see-AY-shun')
    word = re.sub(r'\s*\(["\'][^"\']+["\']\)', '', word)

    # Strip quotes and whitespace again
    word = word.strip().strip('"').strip("'").strip()

    return word


def parse_english_raw_input(text: str) -> List[str]:
    """Parse raw English input text into a list of words/phrases.

    Args:
        text: Raw input text with one word/phrase per line

    Returns:
        List of words/phrases (sanitized and first letter capitalized)
    """
    words: List[str] = []

    for line in text.splitlines():
        line = line.strip()

        # Skip empty lines and comments
        if not line or line.startswith("#"):
            continue

        # Sanitize the word
        word = sanitize_english_word(line)

        # Capitalize first letter
        if word:
            word = word[0].upper() + word[1:] if len(word) > 1 else word.upper()
            words.append(word)

    return words


def process_english_input(
    raw_path: Path,
    output_dir: Path,
    verbose: bool = False,
) -> Path:
    """Process English raw input file and create -input.parsed.csv.
    
    Args:
        raw_path: Path to raw input file
        output_dir: Directory for output files
        verbose: Enable verbose logging
        
    Returns:
        Path to the parsed CSV file
    """
    parsed_path = output_dir / "-input.parsed.csv"
    manifest_key = "-input.parsed.csv"
    
    # Check if already complete
    if is_chunk_complete(output_dir, manifest_key) and parsed_path.exists():
        if verbose:
            print(f"[english] [skip] ✅ Already parsed: {parsed_path.name}")
        return parsed_path
    
    # Read and parse
    text = raw_path.read_text(encoding="utf-8", errors="ignore")
    words = parse_english_raw_input(text)
    
    if verbose:
        print(f"[english] [input] Parsed {len(words)} words from {raw_path.name}")
    
    # Initialize manifest
    init_input_manifest(output_dir, [manifest_key])
    
    # Write CSV (simple format: one word per line)
    output_dir.mkdir(parents=True, exist_ok=True)
    parsed_path.write_text("\n".join(words) + "\n" if words else "", encoding="utf-8")
    
    # Mark complete
    mark_chunk_complete(output_dir, manifest_key)
    
    if verbose:
        print(f"[english] [file] Created {parsed_path.name} ({len(words)} entries)")
    
    return parsed_path

