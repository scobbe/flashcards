"""Common utility functions shared across the library."""

import hashlib
import os
import re
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


# CJK ranges (mirrors is_cjk_char) for regex matching of bare character runs.
_CJK_RANGES = (
    r"㐀-鿿豈-﫿⺀-⻿⼀-⿟"
    r"\U00020000-\U0002ebef\U00030000-\U0003134f"
)
_IDENTICAL_PARENS_RE = re.compile(rf"([{_CJK_RANGES}〇]+)\(([{_CJK_RANGES}〇]+)\)")


def collapse_identical_parens(text: str) -> str:
    """Collapse ``汉字(汉字)`` -> ``汉字`` where the traditional form in parentheses
    merely repeats the preceding (simplified) characters.

    The parenthetical is dropped when it is a suffix of the preceding CJK run
    (the run is greedy, so ``他糾(糾)`` -> ``他糾``). Differing forms like
    ``续(續)`` or ``我的口误(我的口誤)`` are left untouched, and non-CJK
    parentheticals (e.g. pinyin "(shuō, ...)" or "(a picture)") are never
    matched. Used so the rendered card only shows a traditional form when it
    actually differs.
    """
    if not text or "(" not in text:
        return text
    return _IDENTICAL_PARENS_RE.sub(
        lambda m: m.group(1) if m.group(1).endswith(m.group(2)) else m.group(0),
        text,
    )


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

