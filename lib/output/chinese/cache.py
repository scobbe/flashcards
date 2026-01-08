"""Cache management for Chinese flashcard data."""

from pathlib import Path
from typing import Dict, Optional

from lib.common.cache import read_cache as _read_cache, write_cache as _write_cache

CHINESE_CACHE_DIR = Path(__file__).parent.parent.parent.parent / "output" / "chinese" / "cache"
LOG_PREFIX = "chinese"


def get_cache_path(word: str) -> Path:
    """Get the cache file path for a word/character."""
    from lib.common.cache import get_cache_path as _get_cache_path
    return _get_cache_path(CHINESE_CACHE_DIR, word)


def read_cache(word: str, verbose: bool = False) -> Optional[Dict]:
    """Read cached data for a word/character. Returns None if not cached."""
    return _read_cache(CHINESE_CACHE_DIR, word, verbose=verbose, log_prefix=LOG_PREFIX)


def write_cache(word: str, data: Dict, verbose: bool = False) -> None:
    """Write data to cache."""
    _write_cache(CHINESE_CACHE_DIR, word, data, verbose=verbose, log_prefix=LOG_PREFIX)
