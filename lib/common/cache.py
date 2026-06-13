"""Common cache utilities for flashcard data."""

import json
import re
import threading
from pathlib import Path
from typing import Dict, List, Optional


def sanitize_filename(name: str) -> str:
    """Sanitize a string for use as a filename.

    Replaces invalid characters with underscores.
    """
    return re.sub(r'[/\\:*?"<>|]', '_', name)


def get_cache_path(cache_dir: Path, key: str, sanitize: bool = True) -> Path:
    """Get the cache file path for a key.

    Args:
        cache_dir: Base cache directory
        key: Cache key (usually a word)
        sanitize: Whether to sanitize the key for filesystem safety
    """
    safe_key = sanitize_filename(key) if sanitize else key
    return cache_dir / f"{safe_key}.json"


# ---------------------------------------------------------------------------
# In-memory cache layer (avoids re-reading + re-parsing the same hot cache
# files repeatedly within a single run). Kept consistent with disk because all
# writes go through write_cache(), which updates the memo.
# ---------------------------------------------------------------------------

_MEM_LOCK = threading.Lock()
_MEM: Dict[str, Optional[Dict]] = {}  # path_str -> parsed dict, or None for known-missing
_UNSET = object()


def _mem_get(path: Path):
    with _MEM_LOCK:
        return _MEM.get(str(path), _UNSET)


def _mem_set(path: Path, value: Optional[Dict]) -> None:
    with _MEM_LOCK:
        _MEM[str(path)] = value


# ---------------------------------------------------------------------------
# Per-key generation locks. Lets callers serialize the (read -> generate ->
# write) sequence for a single cache key so parallel workers don't redundantly
# regenerate the same shared component (e.g. radicals) and pay for duplicate
# API calls.
# ---------------------------------------------------------------------------

_KEY_LOCKS_LOCK = threading.Lock()
_KEY_LOCKS: Dict[str, threading.Lock] = {}


def key_lock(key: str) -> threading.Lock:
    """Return a process-wide lock unique to ``key`` (created on first use)."""
    with _KEY_LOCKS_LOCK:
        lock = _KEY_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _KEY_LOCKS[key] = lock
        return lock


def read_cache(
    cache_dir: Path,
    key: str,
    required_fields: Optional[List[str]] = None,
    verbose: bool = False,
    log_prefix: str = "cache",
) -> Optional[Dict]:
    """Read cached data for a key. Returns None if not cached or invalid.

    Args:
        cache_dir: Base cache directory
        key: Cache key (usually a word)
        required_fields: If provided, validate these fields exist in cached data
        verbose: Enable verbose logging
        log_prefix: Prefix for log messages (e.g., "english", "chinese")
    """
    cache_path = get_cache_path(cache_dir, key)

    cached = _mem_get(cache_path)
    if cached is _UNSET:
        # Not in memory yet - load from disk once and memoize the result.
        if not cache_path.exists():
            _mem_set(cache_path, None)
            return None
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            # Don't memoize parse errors - the file may be mid-write.
            return None
        _mem_set(cache_path, cached)

    if cached is None:
        return None

    # Validate required fields if specified
    if required_fields and not all(k in cached for k in required_fields):
        return None
    if verbose:
        print(f"[{log_prefix}] [cache] Loaded: {key}")
    return cached


def write_cache(
    cache_dir: Path,
    key: str,
    data: Dict,
    verbose: bool = False,
    log_prefix: str = "cache",
) -> None:
    """Write data to cache.

    Args:
        cache_dir: Base cache directory
        key: Cache key (usually a word)
        data: Data to cache
        verbose: Enable verbose logging
        log_prefix: Prefix for log messages (e.g., "english", "chinese")
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = get_cache_path(cache_dir, key)
    cache_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # Keep the in-memory layer consistent with what we just wrote.
    _mem_set(cache_path, data)
    if verbose:
        print(f"[{log_prefix}] [cache] Saved: {key}")


__all__ = [
    "sanitize_filename",
    "get_cache_path",
    "key_lock",
    "read_cache",
    "write_cache",
]
