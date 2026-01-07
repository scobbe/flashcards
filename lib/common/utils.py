"""Common utility functions shared across the library."""

import hashlib
import os
from pathlib import Path
from typing import Iterable, List, Sequence, Set


_DEF_ENV_LOADED = False


def _load_env_file() -> None:
    """Load environment variables from .env file if present."""
    global _DEF_ENV_LOADED
    if _DEF_ENV_LOADED:
        return
    _DEF_ENV_LOADED = True
    try:
        # Look for .env in lib/common/../.. (project root) or lib/common/..
        here = Path(__file__).parent
        candidates = [
            here.parent.parent / ".env",  # project root
            here.parent / ".env",
            here / ".env",
        ]
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


def is_cjk_char(ch: str) -> bool:
    """Check if a character is a CJK (Chinese/Japanese/Korean) character."""
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


def keep_only_cjk(text: str) -> str:
    """Keep only CJK characters from text."""
    return "".join(ch for ch in text if is_cjk_char(ch))


def line_has_cjk(line: str) -> bool:
    """Check if a line contains any CJK characters."""
    return any(is_cjk_char(ch) for ch in line)


def unique_preserve_order(items: Iterable[str]) -> List[str]:
    """Return unique items while preserving order."""
    seen: Set[str] = set()
    ordered: List[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def filter_substrings(words: Sequence[str]) -> List[str]:
    """Filter out words that are substrings of other words in the list."""
    result: List[str] = []
    for i, w in enumerate(words):
        keep = True
        for j, other in enumerate(words):
            if i == j:
                continue
            if len(other) > len(w) and w and w in other:
                keep = False
                break
        if keep:
            result.append(w)
    return result


def _clean_value(text: str) -> str:
    """Strip control characters that can render as odd glyphs."""
    if not isinstance(text, str):
        return text
    return "".join(ch for ch in text if (ch == "\n" or ch == "\t" or ord(ch) >= 32))


def _sha256_file(path: Path) -> str:
    """Compute SHA256 hash of a file."""
    try:
        with path.open("rb") as f:
            h = hashlib.sha256()
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
            return h.hexdigest()
    except Exception:
        return ""


def ensure_dir(path: Path) -> None:
    """Create directory if it doesn't exist."""
    path.mkdir(parents=True, exist_ok=True)


def simplified_to_traditional(text: str) -> str:
    """Convert simplified Chinese text to traditional Chinese.

    Uses the hanziconv library for reliable character-level conversion.
    Falls back to returning the original text if conversion fails.
    """
    if not text:
        return text
    try:
        from hanziconv import HanziConv
        return HanziConv.toTraditional(text)
    except Exception:
        return text

