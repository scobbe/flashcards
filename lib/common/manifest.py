"""Simplified manifest-based tracking for input and output generation.

Two manifest files:
- -input.manifest.json: Tracks which input chunks are complete
- -output.manifest.json: Tracks which words are complete

Manifest structure:
{
  "file_status": {"1.山": "complete", "2.银": "in_progress", "3.人口": "pending", ...},
  "complete": 5,
  "in_progress": 1,
  "pending": 3,
  "error": 0,
  "complete_contiguous": 4
}

States:
- "pending": Not started
- "in_progress": Currently being processed
- "complete": Successfully finished
- "error": Failed with error
"""

import json
import re
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Set


# Lock for thread-safe manifest updates
MANIFEST_LOCK = threading.Lock()

# Valid states
PENDING = "pending"
IN_PROGRESS = "in_progress"
COMPLETE = "complete"
ERROR = "error"
VALID_STATES = {PENDING, IN_PROGRESS, COMPLETE, ERROR}


def _extract_number(key: str) -> Optional[int]:
    """Extract the leading number from a key like '1.山' or '-input.parsed.001.csv'."""
    # Try pattern like "1.山" or "123.word"
    match = re.match(r'^(\d+)\.', key)
    if match:
        return int(match.group(1))
    # Try pattern like "-input.parsed.001.csv"
    match = re.search(r'\.(\d{3})\.', key)
    if match:
        return int(match.group(1))
    return None


def _compute_complete_contiguous(file_status: Dict[str, str]) -> int:
    """Find the highest contiguous number where all items up to it are complete.

    If there are no numbered items but all items are complete, returns the count of items.
    """
    if not file_status:
        return 0

    # Extract numbers and their completion status
    numbered: Dict[int, bool] = {}
    for key, state in file_status.items():
        num = _extract_number(key)
        if num is not None:
            numbered[num] = (state == COMPLETE)

    # If no numbered items, check if all items are complete
    if not numbered:
        # All complete = count, otherwise 0
        if all(s == COMPLETE for s in file_status.values()):
            return len(file_status)
        return 0

    # Find highest contiguous starting from 1
    highest = 0
    for i in range(1, max(numbered.keys()) + 1):
        if numbered.get(i, False):
            highest = i
        else:
            break
    return highest


def _normalize_state(value: Any) -> str:
    """Normalize a state value, handling legacy boolean format."""
    if isinstance(value, bool):
        return COMPLETE if value else PENDING
    if isinstance(value, str) and value in VALID_STATES:
        return value
    return PENDING


def _compute_stats(file_status: Dict[str, str]) -> Dict[str, Any]:
    """Compute manifest statistics."""
    complete = sum(1 for v in file_status.values() if v == COMPLETE)
    in_progress = sum(1 for v in file_status.values() if v == IN_PROGRESS)
    pending = sum(1 for v in file_status.values() if v == PENDING)
    error = sum(1 for v in file_status.values() if v == ERROR)
    return {
        "file_status": file_status,
        "complete": complete,
        "in_progress": in_progress,
        "pending": pending,
        "error": error,
        "complete_contiguous": _compute_complete_contiguous(file_status),
    }


def _load_manifest(path: Path) -> Dict[str, Any]:
    """Load a manifest file. Returns empty structure if doesn't exist."""
    if not path.exists():
        return {"file_status": {}, "complete": 0, "in_progress": 0, "pending": 0, "error": 0, "complete_contiguous": 0}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            # Handle old format (just file_status dict without wrapper)
            if "file_status" not in data:
                file_status = {k: _normalize_state(v) for k, v in data.items()}
                return _compute_stats(file_status)
            # Ensure file_status exists and normalize states
            raw_status = data.get("file_status", {})
            file_status = {k: _normalize_state(v) for k, v in raw_status.items()}
            return _compute_stats(file_status)
    except Exception:
        pass
    return {"file_status": {}, "complete": 0, "in_progress": 0, "pending": 0, "error": 0, "complete_contiguous": 0}


def _save_manifest(path: Path, file_status: Dict[str, str]) -> None:
    """Save a manifest file, computing stats."""
    output = _compute_stats(file_status)
    path.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8"
    )


#########################################
# Input Manifest (chunk tracking)
#########################################

def input_manifest_path(output_dir: Path) -> Path:
    """Get the input manifest path for an output directory."""
    return output_dir / "-input.manifest.json"


def load_input_manifest(output_dir: Path) -> Dict[str, Any]:
    """Load the input manifest."""
    return _load_manifest(input_manifest_path(output_dir))


def save_input_manifest(output_dir: Path, file_status: Dict[str, str]) -> None:
    """Save the input manifest."""
    _save_manifest(input_manifest_path(output_dir), file_status)


def init_input_manifest(output_dir: Path, chunk_keys: List[str]) -> None:
    """Initialize input manifest with expected chunks (all set to pending).

    Args:
        output_dir: Output directory
        chunk_keys: List of chunk keys like ["-input.parsed.001.csv", "-input.parsed.002.csv", "-input.parsed.csv"]
    """
    with MANIFEST_LOCK:
        file_status = {key: PENDING for key in chunk_keys}
        save_input_manifest(output_dir, file_status)


def is_chunk_complete(output_dir: Path, chunk_key: str) -> bool:
    """Check if a chunk is marked as complete."""
    manifest = load_input_manifest(output_dir)
    file_status = manifest.get("file_status", {})
    return file_status.get(chunk_key) == COMPLETE


def get_chunk_state(output_dir: Path, chunk_key: str) -> str:
    """Get the state of a chunk."""
    manifest = load_input_manifest(output_dir)
    file_status = manifest.get("file_status", {})
    return file_status.get(chunk_key, PENDING)


def mark_chunk_in_progress(output_dir: Path, chunk_key: str) -> None:
    """Mark a chunk as in progress."""
    with MANIFEST_LOCK:
        manifest = load_input_manifest(output_dir)
        file_status = manifest.get("file_status", {})
        file_status[chunk_key] = IN_PROGRESS
        save_input_manifest(output_dir, file_status)


def mark_chunk_complete(output_dir: Path, chunk_key: str) -> None:
    """Mark a chunk as complete."""
    with MANIFEST_LOCK:
        manifest = load_input_manifest(output_dir)
        file_status = manifest.get("file_status", {})
        file_status[chunk_key] = COMPLETE
        save_input_manifest(output_dir, file_status)


def mark_chunk_error(output_dir: Path, chunk_key: str) -> None:
    """Mark a chunk as error."""
    with MANIFEST_LOCK:
        manifest = load_input_manifest(output_dir)
        file_status = manifest.get("file_status", {})
        file_status[chunk_key] = ERROR
        save_input_manifest(output_dir, file_status)


def mark_chunk_incomplete(output_dir: Path, chunk_key: str) -> None:
    """Mark a chunk as pending (for regeneration)."""
    with MANIFEST_LOCK:
        manifest = load_input_manifest(output_dir)
        file_status = manifest.get("file_status", {})
        file_status[chunk_key] = PENDING
        save_input_manifest(output_dir, file_status)


def clear_input_manifest(output_dir: Path) -> None:
    """Clear the input manifest (for full regeneration)."""
    path = input_manifest_path(output_dir)
    if path.exists():
        path.unlink()


#########################################
# Output Manifest (word tracking)
#########################################

def output_manifest_path(output_dir: Path) -> Path:
    """Get the output manifest path for an output directory."""
    return output_dir / "-output.manifest.json"


def load_output_manifest(output_dir: Path) -> Dict[str, Any]:
    """Load the output manifest."""
    return _load_manifest(output_manifest_path(output_dir))


def save_output_manifest(output_dir: Path, file_status: Dict[str, str]) -> None:
    """Save the output manifest."""
    _save_manifest(output_manifest_path(output_dir), file_status)


def init_output_manifest(output_dir: Path, word_keys: List[str]) -> None:
    """Initialize output manifest with expected words (all set to pending).

    Call this at the START of output generation with the full list of expected words.
    MERGES with existing manifest - adds new keys without removing existing ones.

    Args:
        output_dir: Output directory
        word_keys: List of word keys like ["1.山", "2.银", "3.人口"]
    """
    with MANIFEST_LOCK:
        # Load existing to preserve any already-complete items
        manifest = load_output_manifest(output_dir)
        existing_status = manifest.get("file_status", {})

        # MERGE: Start with existing status, then add new keys
        file_status = dict(existing_status)
        for key in word_keys:
            if key not in file_status:
                file_status[key] = PENDING

        save_output_manifest(output_dir, file_status)


def is_word_complete(output_dir: Path, word: str) -> bool:
    """Check if a word is marked as complete."""
    manifest = load_output_manifest(output_dir)
    file_status = manifest.get("file_status", {})
    return file_status.get(word) == COMPLETE


def get_word_state(output_dir: Path, word: str) -> str:
    """Get the state of a word."""
    manifest = load_output_manifest(output_dir)
    file_status = manifest.get("file_status", {})
    return file_status.get(word, PENDING)


def mark_word_in_progress(output_dir: Path, word: str) -> None:
    """Mark a word as in progress."""
    with MANIFEST_LOCK:
        manifest = load_output_manifest(output_dir)
        file_status = manifest.get("file_status", {})
        file_status[word] = IN_PROGRESS
        save_output_manifest(output_dir, file_status)


def mark_word_complete(output_dir: Path, word: str) -> None:
    """Mark a word as complete."""
    with MANIFEST_LOCK:
        manifest = load_output_manifest(output_dir)
        file_status = manifest.get("file_status", {})
        file_status[word] = COMPLETE
        save_output_manifest(output_dir, file_status)


def mark_word_error(output_dir: Path, word: str) -> None:
    """Mark a word as error."""
    with MANIFEST_LOCK:
        manifest = load_output_manifest(output_dir)
        file_status = manifest.get("file_status", {})
        file_status[word] = ERROR
        save_output_manifest(output_dir, file_status)


def mark_word_incomplete(output_dir: Path, word: str) -> None:
    """Mark a word as pending (for regeneration)."""
    with MANIFEST_LOCK:
        manifest = load_output_manifest(output_dir)
        file_status = manifest.get("file_status", {})
        file_status[word] = PENDING
        save_output_manifest(output_dir, file_status)


def clear_output_manifest(output_dir: Path) -> None:
    """Clear the output manifest (for full regeneration)."""
    path = output_manifest_path(output_dir)
    if path.exists():
        path.unlink()


def get_incomplete_words(output_dir: Path, all_words: Set[str]) -> Set[str]:
    """Get set of words that are not marked complete."""
    manifest = load_output_manifest(output_dir)
    file_status = manifest.get("file_status", {})
    return {w for w in all_words if file_status.get(w) != COMPLETE}


def get_complete_words(output_dir: Path) -> Set[str]:
    """Get set of words that are marked complete."""
    manifest = load_output_manifest(output_dir)
    file_status = manifest.get("file_status", {})
    return {w for w, state in file_status.items() if state == COMPLETE}


def get_in_progress_words(output_dir: Path) -> Set[str]:
    """Get set of words that are marked in progress."""
    manifest = load_output_manifest(output_dir)
    file_status = manifest.get("file_status", {})
    return {w for w, state in file_status.items() if state == IN_PROGRESS}


def get_error_words(output_dir: Path) -> Set[str]:
    """Get set of words that are marked as error."""
    manifest = load_output_manifest(output_dir)
    file_status = manifest.get("file_status", {})
    return {w for w, state in file_status.items() if state == ERROR}


def migrate_manifest(path: Path) -> bool:
    """Migrate a manifest file from boolean format to string states.

    Returns True if migration was performed, False if already migrated or no file.
    """
    if not path.exists():
        return False

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return False

        # Check if migration is needed
        file_status = data.get("file_status", data)
        needs_migration = False
        for v in file_status.values():
            if isinstance(v, bool):
                needs_migration = True
                break

        if not needs_migration:
            return False

        # Migrate
        new_status = {k: _normalize_state(v) for k, v in file_status.items()}
        _save_manifest(path, new_status)
        return True
    except Exception:
        return False
