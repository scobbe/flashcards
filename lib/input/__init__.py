"""Input processing library for parsing raw vocabulary files."""

from lib.input.vocab import (
    call_openai_for_vocab_and_forms,
    call_openai_forms_for_words,
    heuristic_extract_headwords,
    extract_phrase_for_word,
)
from lib.input.subwords import (
    call_openai_subwords_for_words,
    format_with_subwords_csv,
)
from lib.input.grammar import (
    call_openai_for_grammar,
    write_parsed_grammar_csv,
)
from lib.input.processing import (
    process_file,
)
from lib.input.english import (
    parse_english_raw_input,
    process_english_input,
)

__all__ = [
    # vocab
    "call_openai_for_vocab_and_forms",
    "call_openai_forms_for_words",
    "heuristic_extract_headwords",
    "extract_phrase_for_word",
    # subwords
    "call_openai_subwords_for_words",
    "format_with_subwords_csv",
    # grammar
    "call_openai_for_grammar",
    "write_parsed_grammar_csv",
    # processing
    "process_file",
    # english
    "parse_english_raw_input",
    "process_english_input",
]

