"""English vocabulary card generation.

English mode produces flashcards for English vocabulary study:
- Front: English word
- Back: Definition, Origin, Pronunciation (non-technical)
- Uses OpenAI to generate all content
"""

from lib.output.english.cards import write_english_card_md, generate_english_card_content
from lib.output.english.processing import process_english_row, process_english_folder, read_english_input

__all__ = [
    "write_english_card_md",
    "generate_english_card_content",
    "process_english_row",
    "process_english_folder",
    "read_english_input",
]

