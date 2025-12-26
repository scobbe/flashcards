"""Common utilities shared across input and output processing."""

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
from lib.common.openai import OpenAIClient

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
    # openai
    "OpenAIClient",
]

