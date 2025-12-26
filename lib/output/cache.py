"""Legacy cache module - deprecated in favor of lib.common.manifest.

This module is kept for backwards compatibility during migration.
All caching is now handled via manifest files.
"""

# Legacy no-op functions for backwards compatibility
def load_global_cache(folder):
    """Deprecated - returns empty dict."""
    return {}

def save_global_cache(folder, cache):
    """Deprecated - no-op."""
    pass

def ensure_words_initialized(cache, bases):
    """Deprecated - no-op."""
    pass

def write_parsed_csv_cache(folder, parsed_path, verbose=False):
    """Deprecated - no-op."""
    pass

def _set_head_md_hash_threadsafe(out_dir, file_base, md_hash):
    """Deprecated - no-op."""
    pass

def init_head_children(out_dir, base, child_bases):
    """Deprecated - no-op."""
    pass

def update_head_child_hash(out_dir, base, child_base, md_hash):
    """Deprecated - no-op."""
    pass

def first_invalid_cached_name_recursive(out_dir, top_base, *, verbose=False):
    """Deprecated - always returns None (nothing invalid)."""
    return None
