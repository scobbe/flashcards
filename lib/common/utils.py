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


# Empty ruby slot for a character whose traditional form equals its simplified
# form. Keeps per-character ruby aligned in Mochi (a bare char would otherwise
# let its neighbor's traditional ruby drift off-center over a multi-char token).
_EMPTY_RUBY = "( )"


def _minimize_trad_pair(simp: str, trad: str, empty_slots: bool = False) -> str:
    """Re-render a ``simp(trad)`` pair so parentheses wrap only differing chars.

    The traditional run aligns to the SUFFIX of the (greedy) simplified run, so
    any leading context is emitted verbatim. A fully-identical run collapses to
    bare text. Otherwise differing characters get ``(traditional)``; identical
    characters are dropped (bare) by default, or given an empty ``( )`` ruby
    slot when ``empty_slots`` is set (used for headings so per-character ruby
    stays centered in Mochi instead of drifting across a multi-char token).

    Examples (simp, trad) -> output:
      (糸, 糸)        -> 糸
      (小学, 小學)     -> 小学(學)          | empty_slots -> 小( )学(學)
      (他糾, 糾)       -> 他糾
    """
    if len(trad) > len(simp):
        return None  # can't align - leave the original untouched
    prefix = simp[: len(simp) - len(trad)]
    s_tail = simp[len(simp) - len(trad):]
    if s_tail == trad:
        return prefix + s_tail  # fully identical -> drop parentheses entirely

    out = [prefix]
    if empty_slots:
        for s_ch, t_ch in zip(s_tail, trad):
            out.append(f"{s_ch}{_EMPTY_RUBY}" if s_ch == t_ch else f"{s_ch}({t_ch})")
    else:
        # Drop identical characters, wrapping each maximal differing run together.
        i, n = 0, len(trad)
        while i < n:
            if s_tail[i] == trad[i]:
                out.append(s_tail[i])
                i += 1
            else:
                j = i
                while j < n and s_tail[j] != trad[j]:
                    j += 1
                out.append(f"{s_tail[i:j]}({trad[i:j]})")
                i = j
    return "".join(out)


def collapse_identical_parens(text: str, empty_slots: bool = False) -> str:
    """Minimize ``汉字(繁體)`` annotations so parentheses wrap only the characters
    whose traditional form differs from the simplified form.

    Fully-identical runs collapse entirely (``糸(糸)`` -> ``糸``); partially
    differing runs keep parentheses only around the differing characters
    (``小学(小學)`` -> ``小学(學)``). With ``empty_slots`` set, identical
    characters instead get an empty ``( )`` ruby slot (``小学(小學)`` ->
    ``小( )学(學)``) so Mochi keeps each character's ruby centered - used for
    heading/breadcrumb lines. Non-CJK parentheticals (pinyin "(shuō, ...)",
    "(a picture)") are never matched.
    """
    if not text or "(" not in text:
        return text

    def _sub(m):
        result = _minimize_trad_pair(m.group(1), m.group(2), empty_slots)
        return result if result is not None else m.group(0)

    return _IDENTICAL_PARENS_RE.sub(_sub, text)


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

