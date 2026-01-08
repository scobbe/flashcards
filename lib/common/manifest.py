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
  "complete_contiguous": 4,
  "raw_input_hash": "abc123..."  # Only in input manifest
}

States:
- "pending": Not started
- "in_progress": Currently being processed
- "complete": Successfully finished
- "error": Failed with error
"""

import hashlib
import json
import re
import shutil
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


def _compute_stats(file_status: Dict[str, str], error_details: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Compute manifest statistics."""
    complete = sum(1 for v in file_status.values() if v == COMPLETE)
    in_progress = sum(1 for v in file_status.values() if v == IN_PROGRESS)
    pending = sum(1 for v in file_status.values() if v == PENDING)
    error = sum(1 for v in file_status.values() if v == ERROR)
    result = {
        "file_status": file_status,
        "complete": complete,
        "in_progress": in_progress,
        "pending": pending,
        "error": error,
        "complete_contiguous": _compute_complete_contiguous(file_status),
    }
    if error_details:
        result["error_details"] = error_details
    return result


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
            error_details = data.get("error_details", {})
            result = _compute_stats(file_status, error_details)
            # Preserve raw_input_hash if present
            if "raw_input_hash" in data:
                result["raw_input_hash"] = data["raw_input_hash"]
            return result
    except Exception:
        pass
    return {"file_status": {}, "complete": 0, "in_progress": 0, "pending": 0, "error": 0, "complete_contiguous": 0}


def _save_manifest(path: Path, file_status: Dict[str, str], error_details: Optional[Dict[str, str]] = None) -> None:
    """Save a manifest file, computing stats."""
    output = _compute_stats(file_status, error_details)
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
    """Load the input manifest.

    Returns dict with file_status and optional raw_input_hash.
    Also computes stats for backwards compatibility.
    """
    path = input_manifest_path(output_dir)
    if not path.exists():
        return {"file_status": {}, "complete": 0, "pending": 0, "in_progress": 0, "error": 0}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            file_status = data.get("file_status", {})
            # Normalize states
            file_status = {k: _normalize_state(v) for k, v in file_status.items()}
            # Compute stats for backwards compatibility
            result = {
                "file_status": file_status,
                "complete": sum(1 for v in file_status.values() if v == COMPLETE),
                "pending": sum(1 for v in file_status.values() if v == PENDING),
                "in_progress": sum(1 for v in file_status.values() if v == IN_PROGRESS),
                "error": sum(1 for v in file_status.values() if v == ERROR),
            }
            if "raw_input_hash" in data:
                result["raw_input_hash"] = data["raw_input_hash"]
            return result
    except Exception:
        pass
    return {"file_status": {}, "complete": 0, "pending": 0, "in_progress": 0, "error": 0}


def save_input_manifest(output_dir: Path, file_status: Dict[str, str], raw_input_hash: Optional[str] = None) -> None:
    """Save the input manifest (simple format without computed stats)."""
    path = input_manifest_path(output_dir)
    # Preserve existing hash if not provided
    if raw_input_hash is None:
        existing = load_input_manifest(output_dir)
        raw_input_hash = existing.get("raw_input_hash")

    output: Dict[str, Any] = {"file_status": file_status}
    if raw_input_hash:
        output["raw_input_hash"] = raw_input_hash
    path.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8"
    )


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


def compute_file_hash(file_path: Path) -> str:
    """Compute SHA256 hash of a file's contents."""
    if not file_path.exists():
        return ""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def get_input_hash(input_parsed_dir: Path) -> Optional[str]:
    """Get the stored raw input hash from the input manifest."""
    manifest = load_input_manifest(input_parsed_dir)
    return manifest.get("raw_input_hash")


def save_input_hash(input_parsed_dir: Path, raw_input_hash: str) -> None:
    """Save the raw input hash to the input manifest."""
    with MANIFEST_LOCK:
        manifest = load_input_manifest(input_parsed_dir)
        file_status = manifest.get("file_status", {})
        save_input_manifest(input_parsed_dir, file_status, raw_input_hash)


def check_and_clear_if_input_changed(raw_input_path: Path, input_parsed_dir: Path, verbose: bool = False) -> bool:
    """Check if raw input file changed and clear input-parsed dir if so.

    Returns True if the directory was cleared (input changed or no hash stored), False otherwise.
    """
    if not raw_input_path.exists():
        return False

    current_hash = compute_file_hash(raw_input_path)
    stored_hash = get_input_hash(input_parsed_dir)

    should_clear = False
    if stored_hash is None:
        # No stored hash - check if parsed CSV exists (legacy state)
        parsed_csv = input_parsed_dir / "-input.parsed.csv"
        if parsed_csv.exists():
            # Legacy: parsed CSV exists but no hash - force re-parse to establish baseline
            if verbose:
                print(f"[input] No input hash stored, clearing {input_parsed_dir} to establish baseline")
            should_clear = True
    elif current_hash != stored_hash:
        # Input file changed
        if verbose:
            print(f"[input] Raw input file changed, clearing {input_parsed_dir}")
        should_clear = True

    if should_clear:
        if input_parsed_dir.exists():
            shutil.rmtree(input_parsed_dir)
            input_parsed_dir.mkdir(parents=True, exist_ok=True)
        return True

    return False


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


def mark_word_error(output_dir: Path, word: str, error_message: Optional[str] = None) -> None:
    """Mark a word as error, optionally with an error message."""
    with MANIFEST_LOCK:
        manifest = load_output_manifest(output_dir)
        file_status = manifest.get("file_status", {})
        error_details = manifest.get("error_details", {})
        file_status[word] = ERROR
        if error_message:
            error_details[word] = error_message
        _save_manifest(output_manifest_path(output_dir), file_status, error_details)


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


def add_subcomponent_error(output_dir: Path, parent_word: str, subcomponent: str, error_message: str) -> None:
    """Add a sub-component error to the manifest.

    Tracks errors for sub-components (like 吕 in 金 in 银) without changing the parent word's status.
    Errors are stored in error_details with key format "parent→subcomponent".
    """
    with MANIFEST_LOCK:
        manifest = load_output_manifest(output_dir)
        file_status = manifest.get("file_status", {})
        error_details = manifest.get("error_details", {})
        error_key = f"{parent_word}→{subcomponent}"
        error_details[error_key] = error_message
        _save_manifest(output_manifest_path(output_dir), file_status, error_details)


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
