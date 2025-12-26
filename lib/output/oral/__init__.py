"""Oral mode card generation.

Oral mode produces simplified flashcards for listening/speaking practice:
- Front: Chinese characters only (no pinyin)
- Back: Pinyin, English definition, and one example sentence
- No etymology, no component decomposition, no sub-word cards
- Uses OpenAI only to generate example sentences
"""

from lib.output.oral.cards import write_oral_card_md
from lib.output.oral.processing import process_oral_row, process_oral_folder

__all__ = [
    "write_oral_card_md",
    "process_oral_row",
    "process_oral_folder",
]

