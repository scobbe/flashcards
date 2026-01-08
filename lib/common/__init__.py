"""Common utilities shared across input and output processing.

Modules:
- utils: String/CJK utilities, file helpers
- logging: Thread-prefixed logging
- config: Folder configuration
- manifest: Processing state tracking
- openai: OpenAI API client

Note: Schemas are in lib/schema/ (chinese.py, english.py)
"""

from lib.common.utils import (
    is_cjk_char,
    keep_only_cjk,
    unique_preserve_order,
    filter_substrings,
    _load_env_file,
    _sha256_file,
    _clean_value,
    ensure_dir,
)
from lib.common.logging import (
    log_debug,
    set_thread_log_context,
    setup_thread_prefixed_stdout,
    set_log_root,
    get_log_root,
    DEFAULT_PARALLEL_WORKERS,
)
from lib.common.config import (
    FolderConfig,
    load_folder_config,
    get_output_dir,
    clear_output_dir_for_no_cache,
    CONFIG_FILENAME,
)
from lib.common.manifest import (
    is_word_complete,
    mark_word_complete,
    mark_word_in_progress,
    mark_word_error,
    init_output_manifest,
    add_subcomponent_error,
    is_chunk_complete,
    mark_chunk_complete,
    init_input_manifest,
    load_input_manifest,
)
from lib.common.openai import OpenAIClient
from lib.common.cache import (
    sanitize_filename,
    get_cache_path,
    read_cache,
    write_cache,
)

__all__ = [
    # utils
    "is_cjk_char",
    "keep_only_cjk",
    "unique_preserve_order",
    "filter_substrings",
    "_load_env_file",
    "_sha256_file",
    "_clean_value",
    "ensure_dir",
    # logging
    "log_debug",
    "set_thread_log_context",
    "setup_thread_prefixed_stdout",
    "set_log_root",
    "get_log_root",
    "DEFAULT_PARALLEL_WORKERS",
    # config
    "FolderConfig",
    "load_folder_config",
    "get_output_dir",
    "clear_output_dir_for_no_cache",
    "CONFIG_FILENAME",
    # manifest
    "is_word_complete",
    "mark_word_complete",
    "mark_word_in_progress",
    "mark_word_error",
    "init_output_manifest",
    "add_subcomponent_error",
    "is_chunk_complete",
    "mark_chunk_complete",
    "init_input_manifest",
    "load_input_manifest",
    # openai
    "OpenAIClient",
    # cache
    "sanitize_filename",
    "get_cache_path",
    "read_cache",
    "write_cache",
]
