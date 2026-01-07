"""Output generation library for flashcard generation.

This package handles Chinese and English flashcard generation.
For Chinese mode, use lib.output.chinese (unified processing).
For English mode, use lib.output.english.
"""

from lib.output.chinese import (
    process_chinese_folder,
    process_chinese_row,
    write_card_md,
    generate_card_content,
    read_parsed_input,
)

# English mode exports
from lib.output.english import (
    write_english_card_md,
    generate_english_card_content,
    process_english_row,
    process_english_folder,
    read_english_input,
)

__all__ = [
    # Chinese mode (unified)
    "process_chinese_folder",
    "process_chinese_row",
    "write_card_md",
    "generate_card_content",
    "read_parsed_input",
    # English mode
    "write_english_card_md",
    "generate_english_card_content",
    "process_english_row",
    "process_english_folder",
    "read_english_input",
]
