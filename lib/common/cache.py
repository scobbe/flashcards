"""Common cache utilities for flashcard data."""

import json
import re
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
    if not cache_path.exists():
        return None
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        # Validate required fields if specified
        if required_fields and not all(k in data for k in required_fields):
            return None
        if verbose:
            print(f"[{log_prefix}] [cache] Loaded: {key}")
        return data
    except Exception:
        return None


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
    if verbose:
        print(f"[{log_prefix}] [cache] Saved: {key}")


__all__ = [
    "sanitize_filename",
    "get_cache_path",
    "read_cache",
    "write_cache",
]
