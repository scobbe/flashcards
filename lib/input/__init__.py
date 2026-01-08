"""Input processing library for parsing raw vocabulary files.

Subpackages:
- lib.input.chinese: Chinese vocabulary parsing
- lib.input.english: English vocabulary parsing
- lib.input.common: Shared input utilities
"""

from lib.input.chinese import (
    call_openai_for_vocab_and_forms,
    call_openai_forms_for_words,
    heuristic_extract_headwords,
    extract_phrase_for_word,
    call_openai_subwords_for_words,
    format_with_subwords_csv,
    call_openai_for_grammar,
    write_parsed_grammar_csv,
    process_file,
)
from lib.input.english import (
    parse_english_raw_input,
    process_english_input,
)

__all__ = [
    # chinese vocab
    "call_openai_for_vocab_and_forms",
    "call_openai_forms_for_words",
    "heuristic_extract_headwords",
    "extract_phrase_for_word",
    # chinese subwords
    "call_openai_subwords_for_words",
    "format_with_subwords_csv",
    # chinese grammar
    "call_openai_for_grammar",
    "write_parsed_grammar_csv",
    # chinese processing
    "process_file",
    # english
    "parse_english_raw_input",
    "process_english_input",
]
