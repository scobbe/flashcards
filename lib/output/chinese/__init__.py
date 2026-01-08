"""Chinese flashcard output generation.

This package handles Chinese flashcard generation:
- cache.py: Cache management for card data
- wiktionary.py: Wiktionary etymology fetching
- cards.py: Card content generation and markdown writing
- processing.py: Row and folder processing
"""

from lib.output.chinese.cards import (
    read_parsed_input,
    generate_card_content,
    write_card_md,
)
from lib.output.chinese.processing import (
    process_chinese_row,
    process_chinese_folder,
)

__all__ = [
    "read_parsed_input",
    "generate_card_content",
    "write_card_md",
    "process_chinese_row",
    "process_chinese_folder",
]
