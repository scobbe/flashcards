"""Folder configuration for flashcard generation.

Each folder can have a -config.json file that specifies:
- output_type: "chinese" or "english" (legacy: "oral", "written" map to "chinese")
- raw_input_file: path to raw input file (default: -input.raw.txt)
- cache: whether to cache files (default: true). When false, clears directory on run.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


CONFIG_FILENAME = "-config.json"


@dataclass
class FolderConfig:
    """Configuration for a flashcard folder."""
    output_type: str  # "chinese" or "english" (legacy: "oral", "written")
    raw_input_file: str = "-input.raw.txt"
    output_dir: str = "../output"  # Path to output directory (relative to config folder)
    cache: bool = True  # When False, clears directory except config and raw input
    chunk_size: Optional[int] = None  # If set, split input into chunks of this size and create subfolders

    def __post_init__(self):
        # Map legacy output types to new unified type
        if self.output_type in ("oral", "written"):
            self.output_type = "chinese"
        if self.output_type not in ("chinese", "english"):
            raise ValueError(f"output_type must be 'chinese' or 'english', got '{self.output_type}'")


def load_folder_config(folder: Path) -> Optional[FolderConfig]:
    """Load configuration from a folder's -config.json file.
    
    Returns None if config file doesn't exist.
    """
    config_path = folder / CONFIG_FILENAME
    if not config_path.exists():
        return None
    
    with open(config_path, encoding="utf-8") as f:
        data = json.load(f)
    
    if not isinstance(data, dict):
        return None
    
    output_type = data.get("output_type", "chinese")
    raw_input_file = data.get("raw_input_file", "-input.raw.txt")
    output_dir = data.get("output_dir", "../output")
    cache = data.get("cache", True)
    chunk_size = data.get("chunk_size", None)

    return FolderConfig(
        output_type=output_type,
        raw_input_file=raw_input_file,
        output_dir=output_dir,
        cache=cache,
        chunk_size=chunk_size,
    )


def write_folder_config(folder: Path, config: FolderConfig) -> Path:
    """Write a configuration file to a folder."""
    config_path = folder / CONFIG_FILENAME
    data = {
        "output_type": config.output_type,
        "raw_input_file": config.raw_input_file,
        "output_dir": config.output_dir,
        "cache": config.cache,
    }
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return config_path


def get_output_dir(config_folder: Path, config: FolderConfig) -> Path:
    """Get the resolved output directory path from config."""
    return (config_folder / config.output_dir).resolve()


def clear_output_dir_for_no_cache(input_folder: Path, config: FolderConfig) -> int:
    """Clear the output/generated folder contents when cache=False.
    
    Returns the number of items cleared.
    """
    output_dir = get_output_dir(input_folder, config)
    if not output_dir.exists():
        return 0
    
    import shutil
    cleared = 0
    
    for item in output_dir.iterdir():
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()
        cleared += 1
    
    return cleared

