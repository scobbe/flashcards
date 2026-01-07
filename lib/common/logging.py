"""Logging utilities for output generation."""

import sys
import threading
from pathlib import Path
from typing import Dict, Optional


# Hardcoded number of parallel workers for output generation
DEFAULT_PARALLEL_WORKERS = 1

# Module-level state
_LOG_ROOT: Optional[Path] = None
_THREAD_IDX_LOCK = threading.Lock()
_THREAD_IDX_MAP: Dict[int, int] = {}
_THREAD_IDX_NEXT = 0

# Thread-local log context (e.g., folder path)
_LOG_CTX = threading.local()


def set_log_root(root: Path) -> None:
    """Set the root path for relative log paths."""
    global _LOG_ROOT
    _LOG_ROOT = root


def get_log_root() -> Optional[Path]:
    """Get the current log root path."""
    return _LOG_ROOT


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


def log_debug(enabled: bool, message: str) -> None:
    """Print a debug message if debugging is enabled."""
    if enabled:
        print(f"[debug] {message}")


class _ThreadPrefixedWriter:
    """Wrapper for stdout that adds thread IDs and context to output."""
    
    def __init__(self, wrapped):
        self._wrapped = wrapped
        self._lock = threading.Lock()

    def write(self, s: str) -> int:
        global _THREAD_IDX_NEXT
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
        
        # Build context tags
        context_tags = f"[{short_tid}]"
        
        if current_file:
            if folder:
                context_tags += f" [./{folder}]"
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
                "cache-hit": "🎯",
                "cache-miss": "💥",
                "api": "🤖",
                "file": "💾",
            }
            return mapping.get(tag, "")
        
        with self._lock:
            parts = s.split("\n")
            has_trailing_newline = len(parts) > 1 and parts[-1] == ""
            
            for i, part in enumerate(parts):
                if part == "" and i == len(parts) - 1:
                    continue
                
                if part.startswith("["):
                    end = part.find("]")
                    if end != -1:
                        tag = part[:end+1]
                        rest = part[end+1:].lstrip()
                        emoji = _emoji_for(part)
                        emoji_spacer = (emoji + " ") if emoji else ""
                        self._wrapped.write(prefix + tag + " " + emoji_spacer + rest)
                    else:
                        self._wrapped.write(prefix + part)
                else:
                    self._wrapped.write(prefix + part)
                
                if i < len(parts) - 1:
                    self._wrapped.write("\n")
            
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


def setup_thread_prefixed_stdout() -> None:
    """Set up thread-prefixed stdout writer."""
    try:
        sys.stdout.reconfigure(line_buffering=True)  # type: ignore
    except Exception:
        pass
    try:
        sys.stdout = _ThreadPrefixedWriter(sys.stdout)  # type: ignore
    except Exception:
        pass

