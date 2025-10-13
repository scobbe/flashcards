import argparse
import os
import sys
import time
import re
import json
import hashlib
from pathlib import Path
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup  # type: ignore
from openai_helper import OpenAIClient
from schema import BACK_SCHEMA, CardField

# Load .env variables (if present) before any OpenAI calls
_DEF_ENV_LOADED = False

def _load_env_file() -> None:
    global _DEF_ENV_LOADED
    if _DEF_ENV_LOADED:
        return
    _DEF_ENV_LOADED = True
    try:
        here = Path(__file__).parent
        candidates = [here / ".env", here.parent / ".env"]
        for p in candidates:
            if not p.exists():
                continue
            for raw in p.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("export "):
                    line = line[len("export "):].strip()
                if "=" not in line:
                    continue
                k, v = line.split("=", 1)
                key = k.strip()
                val = v.strip().strip('"').strip("'")
                if key and os.environ.get(key) is None:
                    os.environ[key] = val
    except Exception:
        pass

# Call once on import
_load_env_file()

# Helpers to extract component English from parent markdown
def _read_md(out_dir: Path, base: str) -> str:
    p = out_dir / f"{base}.md"
    try:
        return p.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def _extract_description_line(md_text: str) -> str:
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
    if not isinstance(md_text, str) or not md_text:
        return ""
    for line in md_text.splitlines():
        line = line.strip()
        if line.startswith("## "):
            return line[3:].strip()
    return ""


# Global lock to serialize writes to the global cache (-output.cache.json)
GLOBAL_CACHE_LOCK = threading.Lock()
_LOG_ROOT: Optional[Path] = None
_REPO_ROOT: Path = Path(__file__).parent.resolve()
_THREAD_IDX_LOCK = threading.Lock()
_THREAD_IDX_MAP: Dict[int, int] = {}
_THREAD_IDX_NEXT = 0
# Thread-local log context (e.g., folder path)
_LOG_CTX = threading.local()

def set_thread_log_context(folder_path: str, current_file: str = "") -> None:
    """Set the logging context for the current thread."""
    try:
        folder_str = folder_path
        try:
            resolved = Path(folder_path).resolve()
            if _LOG_ROOT is not None:
                try:
                    rel = resolved.relative_to(_LOG_ROOT.resolve())
                    folder_str = str(rel)
                except Exception:
                    pass
            # If we ended up with '.' or empty, use just the folder name
            if folder_str in (".", ""):
                folder_str = resolved.name or str(resolved)
        except Exception:
            pass
        _LOG_CTX.folder = folder_str
        _LOG_CTX.current_file = current_file
    except Exception:
        pass

def _set_head_md_hash_threadsafe(out_dir: Path, file_base: str, md_hash: str) -> None:
    with GLOBAL_CACHE_LOCK:
        gcache = load_global_cache(out_dir)
        set_word_md_hash(gcache, file_base, md_hash)
        save_global_cache(out_dir, gcache)

# Ensure logs from worker threads flush promptly to terminal
try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

# Hardcoded number of parallel workers for output generation
DEFAULT_PARALLEL_WORKERS = 5

# Global shared component back-fields cache across threads (keyed by simplified char)
_GLOBAL_COMPONENT_CACHE: Dict[str, object] = {}
_GLOBAL_COMPONENT_CACHE_LOCK = threading.Lock()

def _get_cached_back_for_char(ch: str) -> Optional[object]:
    if not isinstance(ch, str) or not ch:
        return None
    with _GLOBAL_COMPONENT_CACHE_LOCK:
        return _GLOBAL_COMPONENT_CACHE.get(ch)

def _set_cached_back_for_char(ch: str, back: object) -> None:
    if not isinstance(ch, str) or not ch:
        return
    if not isinstance(back, dict):
        return
    with _GLOBAL_COMPONENT_CACHE_LOCK:
        _GLOBAL_COMPONENT_CACHE[ch] = back


class _ThreadPrefixedWriter:
    def __init__(self, wrapped):
        self._wrapped = wrapped
        self._lock = threading.Lock()

    def write(self, s: str) -> int:
        if not isinstance(s, str):
            return 0
        # If this is just a newline from print's second write, don't prefix
        if s == "\n":
            with self._lock:
                try:
                    self._wrapped.write("\n")
                    self._wrapped.flush()
                except Exception:
                    pass
            return 1
        tid = threading.get_ident()
        # Map OS thread id to small stable index t00..t24 etc.
        with _THREAD_IDX_LOCK:
            idx = _THREAD_IDX_MAP.get(tid)
            if idx is None:
                global _THREAD_IDX_NEXT
                idx = _THREAD_IDX_NEXT
                _THREAD_IDX_MAP[tid] = idx
                _THREAD_IDX_NEXT = (_THREAD_IDX_NEXT + 1) % 100
        short_tid = f"t{idx:02d}"
        try:
            folder = getattr(_LOG_CTX, 'folder', '')
            current_file = getattr(_LOG_CTX, 'current_file', '')
        except Exception:
            folder = ''
            current_file = ''
        
        # Build context tags: separate tags for folder, number, and each word component
        # Format: [t01] [1/book] [48] [数] instead of [t01] [1/book/48[数]]
        context_tags = f"[{short_tid}]"
        
        if current_file:
            # Add folder tag
            if folder:
                context_tags += f" [./{folder}]"
            
            # Split file into components: "48.数.娄" -> ["48", "数", "娄"]
            if '.' in current_file:
                parts = current_file.split('.')
                for part in parts:
                    context_tags += f" [{part}]"
            else:
                context_tags += f" [{current_file}]"
        elif folder:
            context_tags += f" [./{folder}]"
        else:
            context_tags += " [main]"
        
        prefix = context_tags + " "
        # Simple emoji mapping for status tags
        def _emoji_for(line: str) -> str:
            try:
                if not line.startswith("["):
                    return ""
                end = line.find("]")
                if end == -1:
                    return ""
                tag = line[1:end]
            except Exception:
                return ""
            mapping = {
                "cache-hit": "🎯",      # Cache hit - completed from cache
                "cache-miss": "💥",     # Cache miss - need to regenerate
                "api": "🤖",           # API call in progress
                "file": "💾",          # File created/written
                # All other tags have no emoji
            }
            return mapping.get(tag, "")
        with self._lock:
            # Split lines and prefix only actual content lines
            parts = s.split("\n")
            has_trailing_newline = len(parts) > 1 and parts[-1] == ""
            
            for i, part in enumerate(parts):
                if part == "" and i == len(parts) - 1:
                    # Skip trailing empty fragment
                    continue
                
                # Extract the first tag from the message part and move emoji after it
                # Format: [tag] emoji message instead of emoji [tag] message
                if part.startswith("["):
                    end = part.find("]")
                    if end != -1:
                        tag = part[:end+1]  # Include the closing bracket
                        rest = part[end+1:].lstrip()  # Rest of message after tag
                        emoji = _emoji_for(part)
                        emoji_spacer = (emoji + " ") if emoji else ""
                        # Write: prefix + tag + emoji + rest
                        self._wrapped.write(prefix + tag + " " + emoji_spacer + rest)
                    else:
                        # No closing bracket, write as-is
                        self._wrapped.write(prefix + part)
                else:
                    # No tag, write as-is
                    self._wrapped.write(prefix + part)
                
                if i < len(parts) - 1:
                    self._wrapped.write("\n")
            
            # If original string had trailing newline, write it now
            if has_trailing_newline:
                self._wrapped.write("\n")
            
            try:
                self._wrapped.flush()
            except Exception:
                pass
        return len(s)

    def flush(self) -> None:
        try:
            self._wrapped.flush()
        except Exception:
            pass

    def isatty(self) -> bool:
        try:
            return bool(self._wrapped.isatty())
        except Exception:
            return False

try:
    sys.stdout = _ThreadPrefixedWriter(sys.stdout)
except Exception:
    pass


def log_debug(enabled: bool, message: str) -> None:
    if enabled:
        print(f"[debug] {message}")


def read_parsed_input(parsed_path: Path) -> List[Tuple[str, str, str, str, str, str]]:
    rows: List[Tuple[str, str, str, str, str, str]] = []
    if parsed_path.suffix.lower() == ".csv":
        import csv
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
    else:
        for line in parsed_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            if "." in line:
                _, rest = line.split(".", 1)
            else:
                rest = line
            pieces = [p.strip() for p in rest.split(",")]
            simp = pieces[0] if len(pieces) > 0 else rest.strip()
            trad = pieces[1] if len(pieces) > 1 else simp
            pin = pieces[2] if len(pieces) > 2 else ""
            eng = pieces[3] if len(pieces) > 3 else ""
            rel = pieces[4] if len(pieces) > 4 else ""
            if simp:
                rows.append((simp, trad, pin, eng, rel))
    return rows


def write_parsed_csv_cache(folder: Path, parsed_path: Path, verbose: bool = False) -> None:
    cache_path = folder / "-input.cache.json"
    try:
        existing: Dict[str, object] = {}
        if cache_path.exists():
            try:
                existing = json.loads(cache_path.read_text(encoding="utf-8"))
                if not isinstance(existing, dict):
                    existing = {}
            except Exception:
                existing = {}
        payload: Dict[str, object] = dict(existing)
        payload["parsed_sha256"] = _sha256_file(parsed_path)
        payload["parsed_file"] = parsed_path.name
        raw_path = folder / "-input.raw.txt"
        if raw_path.exists():
            payload["raw_sha256"] = _sha256_file(raw_path)
        cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if verbose:
            print(f"[file] Updated cache: {cache_path.name}")
    except Exception:
        pass


def wiktionary_url_for_word(word: str) -> str:
    # Use English Wiktionary which contains Chinese entries
    return f"https://en.wiktionary.org/wiki/{requests.utils.requote_uri(word)}"


def fetch_wiktionary_html_status(word: str, timeout: float = 20.0) -> Tuple[str, int]:
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
        # Treat network errors as 0 status with empty body
        return "", 0


def save_html_with_parsed(html_path: Path, html_content: str, verbose: bool = False) -> None:
    """Save both original HTML and parsed version.
    
    Args:
        html_path: Path to save .input.html file
        html_content: Original HTML content
        verbose: Whether to print progress
    """
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
    """Load HTML for API call, preferring parsed version.
    
    Args:
        html_path: Base path (.input.html)
    
    Returns:
        Parsed HTML content if available, otherwise original
    """
    parsed_path = html_path.with_suffix(html_path.suffix + '.parsed')
    
    if parsed_path.exists():
        return parsed_path.read_text(encoding="utf-8", errors="ignore")
    elif html_path.exists():
        # Fallback to original if parsed doesn't exist
        return sanitize_html(html_path.read_text(encoding="utf-8", errors="ignore"))
    else:
        return ""


def sanitize_html(html: str) -> str:
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
    
    # Strategic newlines only for major sections (keep some structure)
    for marker in ["Etymology", "Pronunciation", "Definitions", "Derived terms", 
                  "Compounds", "See also", "References", "Further reading",
                  "Translingual", "Chinese", "Japanese", "Korean", "Vietnamese"]:
        text = text.replace(f" {marker} ", f"\n{marker}: ")
    
    # Remove excessive parenthetical content that's often metadata
    text = re.sub(r'\([^)]{100,}\)', '', text)
    
    # Collapse multiple spaces again after all the removals
    text = re.sub(r'\s+', ' ', text)
    
    # Truncate if still too long
    if len(text) > 20_000:
        text = text[:20_000]
    
    return text.strip()


def _clean_value(text: str) -> str:
    if not isinstance(text, str):
        return text
    # Strip control chars that can render as odd glyphs
    return "".join(ch for ch in text if (ch == "\n" or ch == "\t" or ord(ch) >= 32))


def is_cjk_char(ch: str) -> bool:
    if ch == "〇":
        return True
    code = ord(ch)
    if 0x3400 <= code <= 0x9FFF:
        return True
    if 0xF900 <= code <= 0xFAFF:
        return True
    if 0x2E80 <= code <= 0x2EFF:
        return True
    if 0x2F00 <= code <= 0x2FDF:
        return True
    if 0x20000 <= code <= 0x2EBEF:
        return True
    if 0x30000 <= code <= 0x3134F:
        return True
    return False


def section_header(word: str) -> str:
    return f"<!-- word: {word} -->\n<h1>{word}</h1>\n"


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _parse_component_english_map(description: str) -> Dict[str, str]:
    # Parse tokens like: Simplified(Traditional) (pinyin, "english") and map single CJK simplified char -> english
    mapping: Dict[str, str] = {}
    if not isinstance(description, str) or not description:
        return mapping
    for m in re.finditer(r"([^\s()]+)\s*\([^)]*,\s*\"([^\"]+)\"\)", description):
        token = m.group(1)
        en = m.group(2).strip()
        # Take the first CJK char in the token as the simplified/base
        simp = next((c for c in token if is_cjk_char(c)), "")
        if simp and simp not in mapping:
            mapping[simp] = en
    return mapping


def _parse_component_forms_map(description: str) -> Dict[str, Tuple[str, str]]:
    # Parse tokens like: Simplified(Traditional) (pinyin, "english") to map simplified -> (simplified, traditional)
    mapping: Dict[str, Tuple[str, str]] = {}
    if not isinstance(description, str) or not description:
        return mapping
    # Match: TOKEN [ (TRAD) ] (pinyin, "english")
    pattern = re.compile(r"([^\s()]+)(?:\(([^)]+)\))?\s*\([^)]*,\s*\"[^\"]+\"\)")
    for m in pattern.finditer(description):
        simp_token = m.group(1) or ""
        trad_token = m.group(2) or ""
        simp = next((c for c in simp_token if is_cjk_char(c)), "")
        trad = next((c for c in trad_token if is_cjk_char(c)), "")
        if simp:
            mapping[simp] = (simp, trad or simp)
    return mapping


# Map common radical variants to their primary standalone characters
RADICAL_VARIANT_TO_PRIMARY: Dict[str, str] = {
    "钅": "金",
    "氵": "水",
    "忄": "心",
    "扌": "手",
    "纟": "糸",
    "艹": "艸",
    "饣": "食",
    "讠": "言",
    "阝": "阜",
}

def _map_radical_variant_to_primary(ch: str) -> str:
    return RADICAL_VARIANT_TO_PRIMARY.get(ch, ch)

def _etymology_complete(back: object) -> bool:
    if not isinstance(back, dict):
        return False
    et = back.get("etymology")
    if not isinstance(et, dict):
        return False
    t = et.get("type"); d = et.get("description"); i = et.get("interpretation")
    return isinstance(t, str) and t.strip() and isinstance(d, str) and d.strip() and isinstance(i, str) and i.strip()

def _collect_components_from_back(back_fields: Dict[str, object]) -> List[str]:
    comps: List[str] = []
    if not isinstance(back_fields, dict):
        return comps
    et = back_fields.get("etymology")
    if isinstance(et, dict):
        # Prefer explicit components list if present (schema key normalized)
        raw_present = "component_characters" in et
        raw = et.get("component_characters")
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, str):
                    # Allow values like "金 (钅)"; take the first CJK character
                    first_cjk = next((c for c in item if is_cjk_char(c)), "")
                    if first_cjk:
                        mapped = _map_radical_variant_to_primary(first_cjk)
                        if mapped not in comps:
                            comps.append(mapped)
        # Only fall back to parsing description if the explicit list is ABSENT (not present at all)
        if not comps and not raw_present:
            desc = et.get("description") if isinstance(et.get("description"), str) else ""
            english_map = _parse_component_english_map(str(desc))
            for ch in english_map.keys():
                if len(ch) == 1 and is_cjk_char(ch):
                    mapped = _map_radical_variant_to_primary(ch)
                    if mapped not in comps:
                        comps.append(mapped)
            # Also include every CJK character appearing anywhere in description
            for ch in str(desc):
                if len(ch) == 1 and is_cjk_char(ch):
                    mapped = _map_radical_variant_to_primary(ch)
                    if mapped not in comps:
                        comps.append(mapped)
    return comps


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
    
    # Update log context to show we're working on this component
    set_thread_log_context(str(out_dir), word_id)
    # Skip only if file exists AND cache has matching hash for this child
    expected_hash = ""
    parent_cache = load_head_cache(out_dir, prefix)
    children = parent_cache.get("children") if isinstance(parent_cache, dict) else []
    if isinstance(children, list):
        for c in children:
            if isinstance(c, dict) and c.get("base") == word_id:
                val = c.get("md")
                expected_hash = val if isinstance(val, str) else ""
                break
    actual_hash = _sha256_file(md_path) if md_path.exists() else ""
    if md_path.exists() and expected_hash and actual_hash == expected_hash:
        if verbose:
            print(f"[skip] Component up-to-date: {md_path.name}")
        return
    # Prepare HTML for this component (cached by path)
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

    # Generate back fields for this component (with cache)
    back: Dict[str, object] | object
    # Prefer global shared cache first
    cached_global = _get_cached_back_for_char(target_ch)
    if isinstance(cached_global, dict):
        log_debug(debug, f"global cache hit for component '{target_ch}'")
        back = cached_global
    elif comp_cache is not None and target_ch in comp_cache:
        log_debug(debug, f"local cache hit for component '{target_ch}'")
        back = comp_cache[target_ch]
    else:
        # API call will log details when it happens
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
    # Try to get pinyin from back fields (may be empty); AI fills when not in CSV
    pin = ""
    if isinstance(back, dict):
        pv = back.get("pronunciation")
        if isinstance(pv, str) and pv.strip():
            pin = pv.strip()

    # Write the component markdown with relation header
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
    # Initialize this component's per-head child cache with blank hashes
    child_bases = [f"{word_id}.{sub}" for sub in comps]
    init_head_children(out_dir, word_id, child_bases)
    for sub_ch in comps:
        mapped_sub = _map_radical_variant_to_primary(sub_ch)
        # Prevent self-recursion: skip if child equals current target
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
        # After writing child, update its hash
        child_base = f"{word_id}.{mapped_sub}"
        child_md = out_dir / f"{child_base}.md"
        if child_md.exists():
            update_head_child_hash(out_dir, word_id, child_base, _sha256_file(child_md))
def _field_name_to_key(name: str) -> str:
    # Lowercase, strip parenthetical placeholders, replace spaces/hyphens with underscores
    key = name.lower()
    # Remove parenthetical placeholders like ({traditional})
    while True:
        start = key.find("(")
        end = key.find(")", start + 1)
        if start != -1 and end != -1:
            key = key[:start] + key[end + 1 :]
        else:
            break
    key = key.replace(" ", "_").replace("-", "_")
    key = key.replace("__", "_").strip(" _")
    return key


def _build_back_json_shape() -> str:
    # Include fields whose schema has an ai_prompt; include containers if any child has an ai_prompt
    lines: list[str] = ["{"]
    def add_field(field: CardField, indent: int = 2):
        key = _field_name_to_key(field.name)
        if field.children:
            sublines: list[str] = []
            for ch in field.children or []:
                if ch.ai_prompt is None:
                    continue
                ck = _field_name_to_key(ch.name)
                sublines.append(" " * (indent + 2) + f"\"{ck}\": string,")
            if not sublines:
                return
            lines.append(" " * indent + f"\"{key}\": {{")
            if sublines[-1].strip().endswith(","):
                sublines[-1] = sublines[-1].rstrip(",")
            lines.extend(sublines)
            lines.append(" " * indent + "},")
        else:
            if field.ai_prompt is None:
                return
            # Use field_type to choose primitive type
            if field.field_type == "sublist":
                lines.append(" " * indent + f"\"{key}\": [string, ...],")
            else:
                lines.append(" " * indent + f"\"{key}\": string,")

    for f in BACK_SCHEMA.fields:
        add_field(f)
    if lines[-1].strip().endswith(","):
        lines[-1] = lines[-1].rstrip(",")
    lines.append("}")
    return "\n".join(lines)


def _collect_guidelines() -> str:
    # Use ONLY ai_prompt texts from schema.
    bullets: list[str] = []
    def add_guidance(field: CardField, prefix: str = ""):
        key = _field_name_to_key(field.name)
        if field.ai_prompt:
            bullets.append(f"- {prefix}{key}: {field.ai_prompt}")
        for ch in field.children or []:
            add_guidance(ch, prefix=(prefix + key + ".") if prefix else (key + "."))
    for f in BACK_SCHEMA.fields:
        add_guidance(f)
    return "\n".join(bullets)


def _required_optional_keys() -> tuple[list[str], list[str]]:
    required: list[str] = []
    optional: list[str] = []
    def add_req_opt(field: CardField, prefix: str = ""):
        key = _field_name_to_key(field.name)
        if field.ai_prompt is not None:
            fq = f"{prefix}{key}" if prefix else key
            (required if field.required else optional).append(fq)
        for ch in field.children or []:
            next_prefix = f"{prefix}{key}." if (prefix or field.ai_prompt is not None) else ("" if not key else key + ".")
            # Always traverse children so section fields contribute their ai-prompted children
            add_req_opt(ch, prefix=next_prefix if next_prefix else "")
    for f in BACK_SCHEMA.fields:
        add_req_opt(f)
    return required, optional


def extract_back_fields_from_html(
    simplified: str,
    traditional: str,
    english: str,
    html: str,
    model: Optional[str],
    verbose: bool = False,
    parent_word: Optional[str] = None,
    phrase: str = "",
) -> Dict[str, Dict[str, str] | str]:
    client = OpenAIClient(model=model)
    trad_url = wiktionary_url_for_word(traditional or simplified)
    req, opt = _required_optional_keys()
    system = (
        "You generate back-of-card fields for a Chinese vocabulary flashcard. Output STRICT JSON ONLY matching this shape:\n"
        + _build_back_json_shape()
        + "\nRequired fields: "
        + ", ".join(req)
        + "\nOptional fields: "
        + ", ".join(opt)
        + "\nGuidance (from schema ai_prompts only):\n"
        + _collect_guidelines()
        + "\nHARD CONSTRAINTS:\n"
          "- Return ONLY raw JSON (no markdown, no commentary).\n"
          "- Adhere EXACTLY to field-level guidance from the schema.\n"
          "- If a required value cannot be sourced from the provided HTML (except simplification_rule), return an empty string.\n"
          "- Be concise. Do NOT add extra sentences, labels, or keys.\n"
          "- Do NOT invent facts not present in the HTML (except simplification_rule intuition).\n"
          "- Do NOT change field names or structure.\n"
          "- Use the provided Wiktionary HTML as the PRIMARY source; only the simplification rule may use general knowledge."
    )
    user_parts = [
        "Headword (simplified): " + simplified,
        "Headword (traditional): " + (traditional or simplified),
        "English gloss: " + english,
    ]
    if phrase:
        user_parts.append("Context phrase from source text: " + phrase)
    user_parts.append("Reference URL (traditional form): " + trad_url)
    user_parts.append("\n\nHTML:\n\n" + html)
    user = "\n".join(user_parts)
    if verbose:
        parent_note = f" (component of {parent_word})" if parent_word else ""
        word_display = traditional or simplified
        print(f"[api] Calling OpenAI for '{word_display}'{parent_note} [model={model or 'default'}]")
    _t0 = time.time()
    try:
        data = client.complete_json(system=system, user=user)
    except KeyboardInterrupt:
        # Propagate to top-level clean handler
        raise
    except Exception as e:
        if verbose:
            print(f"[api] OpenAI call failed: {e}")
        data = {}
    _dt_ms = int((time.time() - _t0) * 1000)
    if verbose:
        print(f"[api] OpenAI complete in {_dt_ms} ms")
        try:
            size_kb = len(html.encode('utf-8')) // 1024
        except Exception:
            size_kb = len(html) // 1024
        print(f"[api] HTML bytes (pruned): {size_kb} KB")
    # Build expected JSON structure from schema (defaults)
    def _expected_defaults() -> Dict[str, Dict[str, str] | str | list]:
        out: Dict[str, Dict[str, str] | str | list] = {}
        ctx = {"wiktionary_url": trad_url, "traditional": traditional, "simplified": simplified}
        for f in BACK_SCHEMA.fields:
            key = _field_name_to_key(f.name)
            if f.children:
                # container (e.g., etymology)
                child_obj: Dict[str, str | list] = {}
                for ch in f.children or []:
                    # Include child if it is model-generated OR has a default provider
                    if ch.ai_prompt is None and ch.default_provider is None:
                        continue
                    ck = _field_name_to_key(ch.name)
                    if ch.default_provider is not None:
                        child_obj[ck] = ch.default_provider(ctx)
                    else:
                        child_obj[ck] = [] if ch.field_type == "sublist" else ""
                if child_obj:
                    out[key] = child_obj
            else:
                # leaf
                if f.ai_prompt is None and f.default_provider is None:
                    continue
                if f.default_provider is not None:
                    out[key] = f.default_provider(ctx)
                else:
                    out[key] = [] if f.field_type == "sublist" else ""
        return out

    result: Dict[str, Dict[str, str] | str | list] = _expected_defaults()
    if verbose:
        print("[api] defaults constructed for back fields")

    # Merge model data into expected structure
    if isinstance(data, dict):
        for f in BACK_SCHEMA.fields:
            k = _field_name_to_key(f.name)
            if f.children:
                src = data.get(k)
                if isinstance(src, dict):
                    dst = result.get(k)
                    if isinstance(dst, dict):
                        for ch in f.children or []:
                            if ch.ai_prompt is None:
                                continue
                            ck = _field_name_to_key(ch.name)
                            if ck in src:
                                val = src.get(ck)
                                if ch.field_type == "sublist" and isinstance(val, list):
                                    cleaned_items: List[str] = []
                                    for it in val:
                                        s = str(_clean_value(str(it))).strip()
                                        if s.startswith("- "):
                                            s = s[2:].strip()
                                        if s:
                                            cleaned_items.append(s)
                                    dst[ck] = cleaned_items
                                elif isinstance(val, str):
                                    dst[ck] = _clean_value(val.strip())
            else:
                # Leaf fields: only merge those that are model-generated
                if f.ai_prompt is not None and k in data:
                    val = data.get(k)
                    if f.field_type == "sublist" and isinstance(val, list):
                        cleaned_items: List[str] = []
                        for it in val:
                            s = str(_clean_value(str(it))).strip()
                            if s.startswith("- "):
                                s = s[2:].strip()
                            if s:
                                cleaned_items.append(s)
                        result[k] = cleaned_items
                    elif isinstance(val, str):
                        result[k] = _clean_value(val.strip())
    if verbose:
        print("[api] merge complete; returning back fields")
    # Normalize simplification_rule
    return result  # type: ignore[return-value]


def _sha256_file(path: Path) -> str:
    try:
        with path.open("rb") as f:
            h = hashlib.sha256()
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
            return h.hexdigest()
    except Exception:
        return ""


def _headword_files(out_dir: Path, file_base: str) -> List[Path]:
    # Include top-level and all descendants (md and input.html)
    prefix = f"{file_base}."
    results: List[Path] = []
    # Top-level
    for suffix in (".md",):
        p = out_dir / f"{file_base}{suffix}"
        if p.exists():
            results.append(p)
    # Descendants
    for p in out_dir.iterdir():
        if not p.is_file():
            continue
        name = p.name
        if name.startswith(prefix) and name.endswith(".md"):
            results.append(p)
    return results


def write_headword_cache(out_dir: Path, file_base: str, verbose: bool = False) -> None:
    files = _headword_files(out_dir, file_base)
    mapping: Dict[str, str] = {}
    for p in files:
        mapping[p.name] = _sha256_file(p)
    cache_path = out_dir / f"{file_base}.cache.json"
    cache_path.write_text(json.dumps({"files": mapping}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if verbose:
        print(f"[file] Created cache: {cache_path.name}")


def rebuild_caches_for_folder(folder: Path, verbose: bool = False) -> None:
    """Recompute caches to match on-disk files for ALL levels in this folder.

    - Global cache: top-level heads (N.<word>) md hash
    - Per-head caches: for every parent base that exists on disk, set its immediate children and hashes
    """
    md_files = [p for p in sorted(folder.glob("*.md")) if p.name != "-output.md"]
    stems = [p.stem for p in md_files]
    stems_set = set(stems)

    # Identify top-level heads N.<word> with no extra dots
    heads: List[str] = []
    for st in stems:
        if '.' in st:
            idx, rest = st.split('.', 1)
            if idx.isdigit() and ('.' not in rest):
                heads.append(st)

    # Build mapping: parent_base -> sorted immediate children bases
    parent_to_children: Dict[str, List[str]] = {}
    for st in stems:
        # For each stem, add it as a child of its immediate parent (if any)
        if '.' not in st:
            continue
        parent = st.rsplit('.', 1)[0]
        parent_to_children.setdefault(parent, [])
    # Now fill children lists for each known parent by scanning stems
    for parent in list(parent_to_children.keys()):
        prefix = parent + '.'
        children: List[str] = []
        for st in stems:
            if st.startswith(prefix):
                tail = st[len(prefix):]
                if tail and ('.' not in tail):
                    children.append(st)
        parent_to_children[parent] = sorted(children)

    # Update global cache for heads
    gcache = load_global_cache(folder)
    ensure_words_initialized(gcache, heads)
    for base in heads:
        md_path = folder / f"{base}.md"
        if md_path.exists():
            set_word_md_hash(gcache, base, _sha256_file(md_path))
    save_global_cache(folder, gcache)

    # Update per-head caches for every parent we discovered (all levels)
    for parent, children in parent_to_children.items():
        init_head_children(folder, parent, children)
        for child in children:
            cpath = folder / f"{child}.md"
            if cpath.exists():
                update_head_child_hash(folder, parent, child, _sha256_file(cpath))


def verify_headword_cache(out_dir: Path, file_base: str, verbose: bool = False) -> None:
    # Deprecated destructive verify; kept for compatibility (no-op)
    return


#########################################
# Global cache (-input.cache.json)
#########################################

def _global_cache_path(folder: Path) -> Path:
    return folder / "-output.cache.json"


def load_global_cache(folder: Path) -> Dict[str, object]:
    path = _global_cache_path(folder)
    if not path.exists():
        return {"words": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("words"), list):
            return data
    except Exception:
        pass
    return {"words": []}


def save_global_cache(folder: Path, cache: Dict[str, object]) -> None:
    path = _global_cache_path(folder)
    path.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def ensure_words_initialized(cache: Dict[str, object], bases: List[str]) -> None:
    words = cache.setdefault("words", [])
    assert isinstance(words, list)
    existing = {w.get("base"): w for w in words if isinstance(w, dict)}
    for base in bases:
        if base not in existing:
            words.append({"base": base, "md": ""})


def _find_word_entry(cache: Dict[str, object], base: str) -> Dict[str, object]:
    words = cache.get("words") if isinstance(cache, dict) else None
    if not isinstance(words, list):
        return {}
    for w in words:
        if isinstance(w, dict) and w.get("base") == base:
            return w
    return {}


def set_word_md_hash(cache: Dict[str, object], base: str, md_hash: str) -> None:
    w = _find_word_entry(cache, base)
    if w:
        w["md"] = md_hash


#########################################
# Per-head child cache (one level down)
#########################################

def _head_cache_path(out_dir: Path, base: str) -> Path:
    return out_dir / f"{base}.cache.json"


def load_head_cache(out_dir: Path, base: str) -> Dict[str, object]:
    p = _head_cache_path(out_dir, base)
    if not p.exists():
        return {"children": []}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("children"), list):
            return data
    except Exception:
        pass
    return {"children": []}


def save_head_cache(out_dir: Path, base: str, cache: Dict[str, object]) -> None:
    _head_cache_path(out_dir, base).write_text(
        json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def init_head_children(out_dir: Path, base: str, child_bases: List[str]) -> None:
    cache = load_head_cache(out_dir, base)
    seen = {c.get("base"): c for c in cache.get("children", []) if isinstance(c, dict)}
    children_list: List[Dict[str, str]] = []
    for cb in child_bases:
        children_list.append(seen.get(cb) or {"base": cb, "md": ""})
    cache["children"] = children_list
    save_head_cache(out_dir, base, cache)


def update_head_child_hash(out_dir: Path, base: str, child_base: str, md_hash: str) -> None:
    cache = load_head_cache(out_dir, base)
    children = cache.get("children") if isinstance(cache, dict) else None
    if not isinstance(children, list):
        children = []
    found = False
    for c in children:
        if isinstance(c, dict) and c.get("base") == child_base:
            c["md"] = md_hash
            found = True
            break
    if not found:
        children.append({"base": child_base, "md": md_hash})
    cache["children"] = children
    save_head_cache(out_dir, base, cache)


def remove_head_child(out_dir: Path, base: str, child_base: str) -> None:
    cache = load_head_cache(out_dir, base)
    children = cache.get("children") if isinstance(cache, dict) else None
    if not isinstance(children, list):
        children = []
    children = [c for c in children if not (isinstance(c, dict) and c.get("base") == child_base)]
    cache["children"] = children
    save_head_cache(out_dir, base, cache)


def first_invalid_cached_name(out_dir: Path, file_base: str) -> Optional[str]:
    cache = load_global_cache(out_dir)
    entry = _find_word_entry(cache, file_base)
    head_md = out_dir / f"{file_base}.md"
    md_hash = _sha256_file(head_md) if head_md.exists() else ""
    expected_head = entry.get("md") if isinstance(entry, dict) else ""
    if not isinstance(expected_head, str) or not head_md.exists() or not expected_head or expected_head != md_hash:
        return f"{file_base}.md"
    # Check immediate children only via per-head cache
    hcache = load_head_cache(out_dir, file_base)
    children = hcache.get("children") if isinstance(hcache, dict) else []
    if not isinstance(children, list):
        return None
    for c in children:
        if not isinstance(c, dict):
            continue
        cb = c.get("base")
        chash = c.get("md")
        if not isinstance(cb, str) or not cb:
            continue
        child_md = out_dir / f"{cb}.md"
        if not child_md.exists():
            return f"{cb}.md"
        actual = _sha256_file(child_md)
        if not isinstance(chash, str) or not chash or actual != chash:
            return f"{cb}.md"
    return None


def first_invalid_cached_name_recursive(out_dir: Path, top_base: str, *, verbose: bool = False) -> Optional[str]:
    # Validate the top-level base against the global cache
    bad = first_invalid_cached_name(out_dir, top_base)
    if bad is not None and bad.endswith('.md') and bad[:-3] != top_base:
        # It already found an invalid immediate child
        return bad
    if bad is not None and bad == f"{top_base}.md":
        return bad
    # DFS over children using per-head caches at each depth
    visited: set[str] = set()
    stack: list[str] = [top_base]
    while stack:
        parent = stack.pop()
        if parent in visited:
            continue
        visited.add(parent)
        if verbose and parent != top_base:
            print(f"[check-child] Checking component: {parent}")
        hcache = load_head_cache(out_dir, parent)
        children = hcache.get("children") if isinstance(hcache, dict) else []
        # If the per-head cache is missing or empty, derive children from the filesystem (one level down)
        if not isinstance(children, list) or not children:
            # Discover immediate children by filename pattern: parent.*.md with exactly one extra token
            prefix = parent + "."
            derived: list[Dict[str, str]] = []
            for p in out_dir.iterdir():
                if not p.is_file() or not p.name.endswith(".md"):
                    continue
                stem = p.name[:-3]
                if not stem.startswith(prefix):
                    continue
                tail = stem[len(prefix):]
                if "." in tail:
                    # deeper than one level under this parent
                    continue
                # No cache write here; missing hash is treated as mismatch to force regeneration
                derived.append({"base": stem, "md": ""})
            children = derived
        for c in children:
            if not isinstance(c, dict):
                continue
            cb = c.get("base")
            chash = c.get("md")
            if not isinstance(cb, str) or not cb:
                continue
            child_md = out_dir / f"{cb}.md"
            if not child_md.exists():
                # Instead of regenerating missing children, drop them from the cache
                if verbose:
                    print(f"[mismatch] missing: {cb}.md")
                remove_head_child(out_dir, parent, cb)
                # Continue DFS without forcing regeneration
                continue
            actual = _sha256_file(child_md)
            if not isinstance(chash, str) or not chash or actual != chash:
                if verbose:
                    print(f"[mismatch] hash: {cb}.md")
                return f"{cb}.md"
            stack.append(cb)
    return None


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
    # If the invalid file is the head markdown, rebuild the headword card (normal flow)
    if target_name in (f"{file_base}.md",):
        # Build combined HTML
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
        # Update global cache for head md
        gcache = load_global_cache(out_dir)
        head_md = out_dir / f"{file_base}.md"
        set_word_md_hash(gcache, file_base, _sha256_file(head_md))
        save_global_cache(out_dir, gcache)
        return
    # Otherwise, regenerate the specific sub-component card using subtree generator
    # Parse target name into prefix + last character
    stem = target_name
    if stem.endswith(".md"):
        stem = stem[:-3]
    # stem starts with file_base + optional chain
    if not stem.startswith(file_base + "."):
        return
    chain = stem.split(".")
    # last token is target char; prefix is stem without last token
    if len(chain) < 2:
        return
    target_char = chain[-1]
    parent_prefix = ".".join(chain[:-1])
    # Derive component English and immediate parent English from parent's markdown
    parent_md = _read_md(out_dir, parent_prefix)
    parent_english = _extract_english_heading(parent_md)
    desc_line = _extract_description_line(parent_md)
    comp_eng_map = _parse_component_english_map(desc_line)
    comp_eng = comp_eng_map.get(target_char, "")
    # Initialize visited from ancestor tokens only to prevent cycles.
    # Do NOT include the target child itself, or generation would be skipped.
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
    # Update the immediate parent's cache with this child's hash
    child_base = f"{parent_prefix}.{target_char}"
    child_md = out_dir / f"{child_base}.md"
    if child_md.exists():
        update_head_child_hash(out_dir, parent_prefix, child_base, _sha256_file(child_md))


def build_row_map(rows: List[Tuple[str, str, str, str, str]]) -> Dict[str, Dict[str, str]]:
    mapping: Dict[str, Dict[str, str]] = {}
    for simp, trad, pin, eng, _ in rows:
        card = {"english": eng, "traditional": trad or simp, "simplified": simp or trad, "pinyin": pin}
        if simp and simp not in mapping:
            mapping[simp] = card
        if trad and trad not in mapping:
            mapping[trad] = card
    return mapping


def write_simple_card_md(
    out_dir: Path,
    word: str,
    english: str,
    traditional: str,
    simplified: str,
    pinyin: str,
    relation: str,
    back_fields: Optional[Dict[str, Dict[str, str] | str]] = None,
    verbose: bool = False,
) -> Path:
    md_path = out_dir / f"{word}.md"
    parts: List[str] = []
    # Custom header layout for sub-word and sub-component relations
    rel = relation.strip()
    parent_english = ""
    rel_type = ""
    if rel:
        rel_norm = rel.replace("subword", "sub-word").replace("subcomponent", "sub-component")
        if rel_norm.startswith("sub-word of ") or rel_norm.startswith("sub-component of "):
            rel_type = "sub-word" if rel_norm.startswith("sub-word of ") else "sub-component"
            # Extract parent english between quotes, if present
            q1 = rel_norm.find('"')
            q2 = rel_norm.rfind('"')
            if q1 != -1 and q2 != -1 and q2 > q1:
                parent_english = rel_norm[q1 + 1 : q2]
            # New header layout: child english as H2, relation as H3, parent english as H4
            parts.append(f"## {english}")
            parts.append(f"### {rel_type}")
            if parent_english:
                parts.append(f"#### {parent_english}")
        else:
            # Fallback to original if relation does not match expected pattern
            parts.append(f"## {english}")
            parts.append(f"### {rel_norm}")
    else:
        parts.append(f"## {english}")
    parts.append("---")

    # Helper to render schema label with placeholders
    def render_label(name: str) -> str:
        label = name.replace("{traditional}", traditional).replace("{simplified}", simplified)
        return label

    # Map schema fields by key for access
    name_by_key: Dict[str, str] = {}
    for f in BACK_SCHEMA.fields:
        k = _field_name_to_key(f.name)
        name_by_key[k] = f.name

    # Print the core required fields using schema labels
    for base_key in ("traditional", "simplified", "pronunciation", "definition"):
        label = render_label(name_by_key.get(base_key, base_key))
        if base_key == "definition":
            # Prefer provided english; fallback to AI back_fields if available
            bf_def = ""
            if isinstance(back_fields, dict):
                v = back_fields.get("definition")
                if isinstance(v, str):
                    bf_def = v.strip()
            value = english or bf_def
        elif base_key == "traditional":
            value = traditional
        elif base_key == "simplified":
            value = simplified
        else:
            # pronunciation
            bf_pin = ""
            if isinstance(back_fields, dict):
                v = back_fields.get("pronunciation")
                if isinstance(v, str):
                    bf_pin = v.strip()
            value = pinyin or bf_pin
        parts.append(f"- **{label}:** {value}")

    # Track fields that have already been rendered to avoid duplicates
    rendered_keys = {"traditional", "simplified", "pronunciation", "definition"}

    # AI-derived fields from schema
    if back_fields:
        ctx = {"traditional": traditional, "simplified": simplified}

        def render_field(field: CardField, value: object, indent: int = 0) -> None:
            if callable(getattr(field, "skip_if", None)) and field.skip_if(ctx):
                return
            label = render_label(field.name)
            pad = "  " * indent
            if field.field_type == "section":
                parts.append(f"{pad}- **{label}:**")
                # If section value is missing from model output, still render its children from defaults
                section_val = value if isinstance(value, dict) else {}
                for ch in field.children or []:
                    ck = _field_name_to_key(ch.name)
                    render_field(ch, section_val.get(ck), indent + 1)
                return
            # For non-section leaves/sublists, require ai_prompt OR a default_provider (schema-driven)
            if field.ai_prompt is None and field.default_provider is None:
                return
            if field.field_type == "sublist":
                items = value if isinstance(value, list) else []
                # Enforce max_items if provided by schema
                try:
                    max_items = getattr(field, "max_items", None)
                except Exception:
                    max_items = None
                if isinstance(max_items, int) and max_items > 0:
                    items = items[:max_items]
                # If this is component_characters and items is empty but description exists,
                # synthesize items from all CJK characters in etymology.description
                try:
                    fk = _field_name_to_key(field.name)
                except Exception:
                    fk = ""
                if fk == "component_characters" and not items:
                    try:
                        et = back_fields.get("etymology") if isinstance(back_fields, dict) else None
                        desc_any = et.get("description") if isinstance(et, dict) else ""
                        synthesized: List[str] = []
                        for ch in str(desc_any):
                            if len(ch) == 1 and is_cjk_char(ch):
                                mapped = _map_radical_variant_to_primary(ch)
                                if mapped not in synthesized:
                                    synthesized.append(mapped)
                        items = synthesized
                    except Exception:
                        pass
                # Always print the header line for sublists
                parts.append(f"{pad}- **{label}:**")
                if items:
                    for item in items:
                        parts.append(f"{pad}  - {str(item)}")
                else:
                    fallback = getattr(field, "empty_fallback", None) or ""
                    # Special-case: for component characters, use a different fallback for multi-character headwords
                    if fk == "component_characters":
                        simp_len = len((ctx.get("simplified") or ""))
                        trad_len = len((ctx.get("traditional") or ""))
                        is_compound = max(simp_len, trad_len) > 1
                        if is_compound:
                            fallback = "None, compound word"
                    if fallback:
                        parts.append(f"{pad}  - {fallback}")
                return
            # line
            if isinstance(value, str) and value.strip():
                clean = _clean_value(value.strip())
                parts.append(f"{pad}- **{label}:** {clean}")

        # Render all AI-generated fields at top level (including sections)
        # Render all fields from schema using field types; avoid re-rendering already printed core fields
        for f in BACK_SCHEMA.fields:
            k = _field_name_to_key(f.name)
            if k in rendered_keys:
                continue
            v = back_fields.get(k) if isinstance(back_fields, dict) else None
            render_field(f, v, indent=0)
    parts.append("%%%")
    content = "\n".join(parts) + "\n"
    md_path.write_text(content, encoding="utf-8")
    if verbose:
        print(f"[file] Created: {md_path.name}")
    return md_path


def render_grammar_folder_cards(folder: Path, verbose: bool = False) -> int:
    import csv, json as _json
    path = folder / "-input.parsed.grammar.csv"
    if not path.exists():
        return 0
    written = 0
    with path.open("r", encoding="utf-8") as f:
        reader = csv.reader(f)
        for idx, row in enumerate(reader, start=1):
            try:
                desc = (row[0] if len(row) > 0 else "").strip()
                usage_cn = (row[1] if len(row) > 1 else "").strip()
                ex_json = (row[2] if len(row) > 2 else "[]").strip()
                try:
                    examples = _json.loads(ex_json)
                except Exception:
                    examples = []
                if not isinstance(examples, list):
                    examples = []
            except Exception:
                continue
            if not desc:
                continue
            base = f"G{idx}.grammar"
            md_path = folder / f"{base}.md"
            parts: List[str] = []
            parts.append(f"## {desc}")
            parts.append(f"### grammar rule")
            parts.append("---")
            parts.append(f"- **description:** {desc}")
            parts.append(f"- **usage in Chinese:** {usage_cn}")
            parts.append(f"- **examples:**")
            for ex in examples:
                parts.append(f"  - {str(ex)}")
            parts.append("%%%")
            content = "\n".join(parts) + "\n"
            md_path.write_text(content, encoding="utf-8")
            written += 1
            if verbose:
                print(f"[ok] Grammar card: {md_path.name}")
    # Append to -output.md
    try:
        output_md = folder / "-output.md"
        md_files = [p for p in sorted(folder.glob("*.md")) if p.name != "-output.md"]
        parts2: List[str] = []
        for p in md_files:
            try:
                parts2.append(p.read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                continue
        output_md.write_text("\n\n".join(parts2) + ("\n" if parts2 else ""), encoding="utf-8")
        if verbose:
            print(f"[ok] Wrote {output_md.name} ({len(parts2)} files)")
    except Exception:
        pass
    return written


def render_grammar_folder(folder: Path, verbose: bool = False) -> None:
    render_grammar_folder_cards(folder, verbose=verbose)


def _process_single_row(
    folder: Path,
    idx: int,
    simp: str,
    trad: str,
    pin: str,
    eng: str,
    phrase: str,
    rel: str,
    model: Optional[str],
    verbose: bool,
    debug: bool,
    delay_s: float,
    comp_cache: Dict[str, object],
) -> Tuple[int, int]:
    # Returns (words_processed, cards_created_increment)
    headword = simp or trad
    file_base = f"{idx}.{headword}"
    out_dir = folder
    md_path = out_dir / f"{file_base}.md"
    successes_local = 0
    
    # Set log context for this thread with current file
    set_thread_log_context(str(folder), file_base)
    
    if md_path.exists():
        if verbose:
            print(f"[check] Checking: {file_base}")
        repair_iter = 0
        while True:
            bad = first_invalid_cached_name_recursive(out_dir, file_base, verbose=verbose)
            if bad is None:
                if verbose:
                    print(f"[cache-hit] Completed: {file_base}")
                break
            if verbose:
                print(f"[cache-miss] Rebuilding: {bad}")
            # Defensive: if regeneration target is the head md and only hash mismatch, update cache instead
            if bad == f"{file_base}.md" and md_path.exists():
                # Update global cache hash to current file without re-generating
                _set_head_md_hash_threadsafe(out_dir, file_base, _sha256_file(md_path))
                # Re-check after updating hash
                repair_iter += 1
                if repair_iter > 200:
                    raise RuntimeError(f"repair loop exceeded limit for {file_base}")
                continue
            # If the target is an immediate or nested child and the file exists, update the parent's child hash
            if bad.endswith('.md'):
                child_stem = bad[:-3]
                child_path = out_dir / f"{child_stem}.md"
                if child_path.exists():
                    parent = child_stem.rsplit('.', 1)[0] if '.' in child_stem else file_base
                    update_head_child_hash(out_dir, parent, child_stem, _sha256_file(child_path))
                    repair_iter += 1
                    if repair_iter > 200:
                        raise RuntimeError(f"repair loop exceeded limit for {file_base}")
                    continue
            regenerate_single_file(
                out_dir=out_dir,
                file_base=file_base,
                target_name=bad,
                simp=simp,
                trad=trad,
                eng=eng,
                model=model,
                verbose=verbose,
                debug=debug,
                delay_s=delay_s,
            )
            repair_iter += 1
            if repair_iter > 200:
                raise RuntimeError(f"repair loop exceeded limit for {file_base}")
        return 1, 0
    # Build combined HTML fresh
    combined_sections: List[str] = []
    fetched_set: Dict[str, bool] = {}
    for form in [simp, trad]:
        form = (form or "").strip()
        if not form or form in fetched_set:
            continue
        fetched_set[form] = True
        form_html, form_status = fetch_wiktionary_html_status(form)
        if verbose:
            print(f"[info] Wiktionary GET {form} -> {form_status}")
        if form_status == 200 and form_html:
            combined_sections.append(section_header(form) + form_html)
        else:
            combined_sections.append(section_header(form))
        if delay_s > 0:
            time.sleep(delay_s)
    combined_html_raw = "\n\n".join(combined_sections)
    
    # Save both original and parsed HTML
    html_path = out_dir / f"{file_base}.input.html"
    save_html_with_parsed(html_path, combined_html_raw, verbose=verbose)
    
    # Use parsed version for API
    combined_html = load_html_for_api(html_path)
    
    if verbose:
        log_debug(debug, f"combined html size for {file_base}: {len(combined_html)}")
    log_debug(debug, f"calling extract_back_fields_from_html for {headword}; pinyin='{pin}'; HTML bytes={len(combined_html)}")
    back = extract_back_fields_from_html(
        simplified=simp or trad,
        traditional=trad or simp,
        english=eng,
        html=combined_html,
        model=model,
        verbose=verbose,
        parent_word=None,
        phrase=phrase,
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
            phrase=phrase,
        )
    if verbose:
        et = back.get("etymology") if isinstance(back, dict) else None
        et_type = et.get("type") if isinstance(et, dict) else ""
        et_sr = et.get("simplification_rule") if isinstance(et, dict) else ""
        sr_flag = "present" if (simp and trad and simp != trad and et_sr) else "skipped"
        print(f"[ok] Back fields extracted: etymology.type='{et_type}', simplification={sr_flag}")
    log_debug(debug, f"back keys for {headword}: {list(back.keys()) if isinstance(back, dict) else type(back)}")
    write_simple_card_md(
        out_dir,
        file_base,
        eng,
        trad or headword,
        simp or headword,
        pin,
        rel,
        back_fields=back,
    )
    _set_head_md_hash_threadsafe(out_dir, file_base, _sha256_file(md_path))
    log_debug(debug, f"wrote md for {file_base}: pinyin='{pin}', relation='{rel}'")
    try:
        if isinstance(back, dict) and isinstance(headword, str) and len(headword) == 1:
            comp_list = _collect_components_from_back(back)
            log_debug(debug, f"components for {headword}: {comp_list}")
            if comp_list:
                desc = (
                    back.get("etymology", {}).get("description")
                    if isinstance(back.get("etymology"), dict)
                    else ""
                )
                english_map = _parse_component_english_map(str(desc))
                forms_map = _parse_component_forms_map(str(desc))
                visited: set = set([headword])
                child_bases = [f"{file_base}.{ch}" for ch in comp_list]
                init_head_children(out_dir, file_base, child_bases)
                for ch in comp_list:
                    log_debug(debug, f"recurse into {file_base}.{ch} english='{english_map.get(ch, '')}'")
                    sub_simp, sub_trad = forms_map.get(ch, (ch, ch))
                    cached_global = _get_cached_back_for_char(ch)
                    if isinstance(cached_global, dict):
                        comp_cache[ch] = cached_global
                    _generate_component_subtree(
                        out_dir=out_dir,
                        prefix=file_base,
                        ch=ch,
                        component_english=english_map.get(ch, ""),
                        parent_english=eng,
                        model=model,
                        verbose=verbose,
                        debug=debug,
                        delay_s=delay_s,
                        visited=visited,
                        depth=1,
                        comp_cache=comp_cache,
                        simp_form=sub_simp,
                        trad_form=sub_trad,
                    )
                    child_base = f"{file_base}.{ch}"
                    child_md = out_dir / f"{child_base}.md"
                    if child_md.exists():
                        update_head_child_hash(out_dir, file_base, child_base, _sha256_file(child_md))
                repair_iter = 0
                while True:
                    bad2 = first_invalid_cached_name_recursive(out_dir, file_base, verbose=verbose)
                    if bad2 is None:
                        break
                    if verbose:
                        print(f"[regen] Rebuilding: {bad2}")
                    regenerate_single_file(
                        out_dir=out_dir,
                        file_base=file_base,
                        target_name=bad2,
                        simp=simp,
                        trad=trad,
                        eng=eng,
                        model=model,
                        verbose=verbose,
                        debug=debug,
                        delay_s=delay_s,
                    )
                    repair_iter += 1
                    if repair_iter > 200:
                        raise RuntimeError(f"repair loop exceeded limit for {file_base}")
    except Exception as e:
        if verbose:
            print(f"[warn] sub-component generation failed for {file_base}: {e}")
        raise
    successes_local += 1
    if verbose:
        print(f"[ok] Card for {file_base}")
    return 1, successes_local


def process_folder(folder: Path, model: Optional[str], verbose: bool, debug: bool, delay_s: float) -> Tuple[int, int]:
    # Only support the canonical filename: -input.parsed.csv
    parsed_path = folder / "-input.parsed.csv"
    if not parsed_path.exists():
        if verbose:
            print(f"[skip] No -input.parsed.csv in {folder}")
        return 0, 0
    rows = read_parsed_input(parsed_path)
    # Persist current parsed CSV hash for idempotence tracking
    write_parsed_csv_cache(folder, parsed_path, verbose)
    if verbose:
        print(f"[info] Processing {len(rows)} vocabulary words from {folder.name}/")
    log_debug(debug, f"parsed rows sample: {rows[:3]}")
    out_dir = folder
    successes = 0
    comp_cache: Dict[str, object] = {}
    # Initialize global cache for all words upfront with blank hashes
    file_bases = [f"{i}.{(s or t)}" for i, (s, t, *_rest) in enumerate(rows, start=1)]
    gcache = load_global_cache(out_dir)
    ensure_words_initialized(gcache, file_bases)
    save_global_cache(out_dir, gcache)

    # Determine concurrency level (hardcoded)
    workers = DEFAULT_PARALLEL_WORKERS

    if workers == 1:
        for idx, (simp, trad, pin, eng, phrase, rel) in enumerate(rows, start=1):
            try:
                _, inc = _process_single_row(folder, idx, simp, trad, pin, eng, phrase, rel, model, verbose, debug, delay_s, comp_cache)
                successes += inc
            except KeyboardInterrupt:
                if verbose:
                    print("[cancelled]")
                return successes, len(rows)
            except Exception as e:
                if verbose:
                    print(f"[error] Failed to build card for {(simp or trad)}: {e}")
                raise
    else:
        if verbose:
            print(f"[info] Parallel workers: {workers}")
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = []
            for idx, (simp, trad, pin, eng, phrase, rel) in enumerate(rows, start=1):
                futures.append(
                    executor.submit(
                        _process_single_row,
                        folder,
                        idx,
                        simp,
                        trad,
                        pin,
                        eng,
                        phrase,
                        rel,
                        model,
                        verbose,
                        debug,
                        delay_s,
                        comp_cache,
                    )
                )
            try:
                for fut in as_completed(futures):
                    words_inc, cards_inc = fut.result()
                    successes += cards_inc
            except KeyboardInterrupt:
                if verbose:
                    print("[cancelled]")
                # Let threads wind down naturally
            except Exception as e:
                if verbose:
                    print(f"[error] Worker failed: {e}")
                raise
    # After processing the folder, concatenate all .md files into -output.md
    try:
        output_md = out_dir / "-output.md"
        md_files = [p for p in sorted(out_dir.glob("*.md")) if p.name != "-output.md"]
        parts: List[str] = []
        for p in md_files:
            try:
                parts.append(p.read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                if verbose:
                    print(f"[warn] failed reading {p.name} for -output.md")
        content = "\n\n".join(parts) + ("\n" if parts else "")
        output_md.write_text(content, encoding="utf-8")
        if verbose:
            print(f"[ok] Wrote {output_md.name} ({len(content)} bytes) with {len(md_files)} files")
    except Exception as e:
        if verbose:
            print(f"[warn] failed to write -output.md: {e}")
    return len(rows), successes


def find_parsed_folders(root: Path) -> List[Path]:
    # Only support the canonical filename: -input.parsed.csv
    folders: List[Path] = []
    seen = set()
    for path in root.rglob("-input.parsed.csv"):
        parent = Path(path).parent
        if parent not in seen:
            folders.append(parent)
            seen.add(parent)
    folders.sort()
    return folders


def find_grammar_folders(root: Path) -> List[Path]:
    folders: List[Path] = []
    seen = set()
    for path in root.rglob("-input.parsed.grammar.csv"):
        parent = Path(path).parent
        if parent not in seen:
            folders.append(parent)
            seen.add(parent)
    folders.sort()
    return folders


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate flashcard .md files from parsed vocab (one-to-one) and fetch combined HTML")
    parser.add_argument(
        "--root",
        default=str(Path(__file__).parent / "output"),
        help="Root directory to scan (default: ./output)",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("OPENAI_MODEL"),
        help="OpenAI model name (overrides OPENAI_MODEL)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.0,
        help="Optional delay in seconds between requests to Wiktionary",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable extremely verbose debugging logs",
    )
    parser.add_argument(
        "--rebuild-caches-only",
        action="store_true",
        help="Recompute and rewrite cache files to match current markdown files without regeneration",
    )
    args = parser.parse_args(argv)

    root = Path(args.root)
    # Configure log root for relative folder paths
    try:
        global _LOG_ROOT
        _LOG_ROOT = root
    except Exception:
        pass
    if not root.exists():
        print(f"[main] [error] Root directory does not exist: {root}", file=sys.stderr)
        return 2

    try:
        if args.rebuild_caches_only:
            if args.verbose:
                print(f"[main] [info] Rebuilding caches under {root}")
            for folder in sorted({p.parent for p in root.rglob('*.md')}):
                rebuild_caches_for_folder(folder, verbose=args.verbose)
            if args.verbose:
                print("[main] [done] Cache rebuild complete")
            return 0
        folders = find_parsed_folders(root)
        grammar_folders = find_grammar_folders(root)
        
        if args.verbose or args.debug:
            print("\n" + "=" * 80)
            print(f"🚀 Flashcard Generator")
            print("=" * 80)
            print(f"📁 Root: {root}")
            print(f"📝 Found {len(folders)} vocab folder(s)")
            print(f"📚 Found {len(grammar_folders)} grammar folder(s)")
            print(f"🤖 Model: {args.model or 'default'}")
            print(f"⚡ Workers: {DEFAULT_PARALLEL_WORKERS}")
            print("=" * 80 + "\n")
        
        total_words = 0
        total_cards = 0
        total_cached = 0
        total_api_calls = 0
        
        for folder_idx, folder in enumerate(folders, 1):
            if args.verbose:
                print(f"\n{'─' * 80}")
                print(f"📂 Processing folder {folder_idx}/{len(folders)}: {folder}")
                print(f"{'─' * 80}\n")
            
            words, cards = process_folder(folder, args.model, args.verbose, args.debug, args.delay)
            total_words += words
            total_cards += cards
            
            if args.verbose:
                print(f"\nFolder complete: {words} words processed, {cards} cards generated\n")
        # Render grammar cards
        for gfolder in grammar_folders:
            try:
                render_grammar_folder(gfolder, args.verbose)
            except Exception as e:
                if args.verbose:
                    print(f"[main] [warn] grammar rendering failed in {gfolder}: {e}")

        if args.verbose or args.debug:
            print(f"\n{'=' * 80}")
            print(f"✅ Processing Complete!")
            print(f"{'=' * 80}")
            print(f"📊 Summary:")
            print(f"   • Folders processed: {len(folders)}")
            print(f"   • Words processed: {total_words}")
            print(f"   • Cards created: {total_cards}")
            print(f"{'=' * 80}\n")
        return 0
    except KeyboardInterrupt:
        print("[main] [info] Interrupted by user (Ctrl-C). Exiting cleanly.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())


