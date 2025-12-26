"""Simplified manifest-based tracking for input and output generation.

Two manifest files:
- -input.manifest.json: Tracks which input chunks are complete
- -output.manifest.json: Tracks which words are complete

Manifest structure:
{
  "file_status": {"1.山": true, "2.银": false, ...},
  "complete": 5,
  "remaining": 3,
  "complete_contiguous": 4
}
"""

import json
import re
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Set


# Lock for thread-safe manifest updates
MANIFEST_LOCK = threading.Lock()


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


def _compute_complete_contiguous(file_status: Dict[str, bool]) -> int:
    """Find the highest contiguous number where all items up to it are complete.
    
    If there are no numbered items but all items are complete, returns the count of items.
    """
    if not file_status:
        return 0
    
    # Extract numbers and their completion status
    numbered: Dict[int, bool] = {}
    for key, complete in file_status.items():
        num = _extract_number(key)
        if num is not None:
            numbered[num] = complete
    
    # If no numbered items, check if all items are complete
    if not numbered:
        # All complete = count, otherwise 0
        if all(file_status.values()):
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


def _compute_stats(file_status: Dict[str, bool]) -> Dict[str, Any]:
    """Compute manifest statistics."""
    complete = sum(1 for v in file_status.values() if v)
    remaining = sum(1 for v in file_status.values() if not v)
    return {
        "file_status": file_status,
        "complete": complete,
        "remaining": remaining,
        "complete_contiguous": _compute_complete_contiguous(file_status),
    }


def _load_manifest(path: Path) -> Dict[str, Any]:
    """Load a manifest file. Returns empty structure if doesn't exist."""
    if not path.exists():
        return {"file_status": {}, "complete": 0, "remaining": 0, "complete_contiguous": 0}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            # Handle old format (just file_status dict without wrapper)
            if "file_status" not in data:
                file_status = {k: bool(v) for k, v in data.items()}
                return _compute_stats(file_status)
            # Ensure file_status exists
            file_status = data.get("file_status", {})
            return _compute_stats(file_status)
    except Exception:
        pass
    return {"file_status": {}, "complete": 0, "remaining": 0, "complete_contiguous": 0}


def _save_manifest(path: Path, file_status: Dict[str, bool]) -> None:
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


def save_input_manifest(output_dir: Path, file_status: Dict[str, bool]) -> None:
    """Save the input manifest."""
    _save_manifest(input_manifest_path(output_dir), file_status)


def init_input_manifest(output_dir: Path, chunk_keys: List[str]) -> None:
    """Initialize input manifest with expected chunks (all set to false).
    
    Args:
        output_dir: Output directory
        chunk_keys: List of chunk keys like ["-input.parsed.001.csv", "-input.parsed.002.csv", "-input.parsed.csv"]
    """
    with MANIFEST_LOCK:
        file_status = {key: False for key in chunk_keys}
        save_input_manifest(output_dir, file_status)


def is_chunk_complete(output_dir: Path, chunk_key: str) -> bool:
    """Check if a chunk is marked as complete."""
    manifest = load_input_manifest(output_dir)
    file_status = manifest.get("file_status", {})
    return file_status.get(chunk_key, False)


def mark_chunk_complete(output_dir: Path, chunk_key: str) -> None:
    """Mark a chunk as complete."""
    with MANIFEST_LOCK:
        manifest = load_input_manifest(output_dir)
        file_status = manifest.get("file_status", {})
        file_status[chunk_key] = True
        save_input_manifest(output_dir, file_status)


def mark_chunk_incomplete(output_dir: Path, chunk_key: str) -> None:
    """Mark a chunk as incomplete (for regeneration)."""
    with MANIFEST_LOCK:
        manifest = load_input_manifest(output_dir)
        file_status = manifest.get("file_status", {})
        file_status[chunk_key] = False
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


def save_output_manifest(output_dir: Path, file_status: Dict[str, bool]) -> None:
    """Save the output manifest."""
    _save_manifest(output_manifest_path(output_dir), file_status)


def init_output_manifest(output_dir: Path, word_keys: List[str]) -> None:
    """Initialize output manifest with expected words (all set to false).
    
    Call this at the START of output generation with the full list of expected words.
    
    Args:
        output_dir: Output directory
        word_keys: List of word keys like ["1.山", "2.银", "3.人口"]
    """
    with MANIFEST_LOCK:
        # Load existing to preserve any already-complete items
        manifest = load_output_manifest(output_dir)
        existing_status = manifest.get("file_status", {})
        
        # Initialize all expected words, keeping existing complete status
        file_status = {}
        for key in word_keys:
            file_status[key] = existing_status.get(key, False)
        
        save_output_manifest(output_dir, file_status)


def is_word_complete(output_dir: Path, word: str) -> bool:
    """Check if a word is marked as complete.
    
    For oral mode: Complete when card is generated.
    For written mode: Complete when card AND all recursive decomposition are done.
    """
    manifest = load_output_manifest(output_dir)
    file_status = manifest.get("file_status", {})
    return file_status.get(word, False)


def mark_word_complete(output_dir: Path, word: str) -> None:
    """Mark a word as complete."""
    with MANIFEST_LOCK:
        manifest = load_output_manifest(output_dir)
        file_status = manifest.get("file_status", {})
        file_status[word] = True
        save_output_manifest(output_dir, file_status)


def mark_word_incomplete(output_dir: Path, word: str) -> None:
    """Mark a word as incomplete (for regeneration)."""
    with MANIFEST_LOCK:
        manifest = load_output_manifest(output_dir)
        file_status = manifest.get("file_status", {})
        file_status[word] = False
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
    return {w for w in all_words if not file_status.get(w, False)}


def get_complete_words(output_dir: Path) -> Set[str]:
    """Get set of words that are marked complete."""
    manifest = load_output_manifest(output_dir)
    file_status = manifest.get("file_status", {})
    return {w for w, complete in file_status.items() if complete}
