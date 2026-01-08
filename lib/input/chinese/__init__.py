"""Chinese input processing - parsing raw vocabulary files."""

from lib.input.chinese.vocab import (
    call_openai_for_vocab_and_forms,
    call_openai_forms_for_words,
    heuristic_extract_headwords,
    extract_phrase_for_word,
)
from lib.input.chinese.subwords import (
    call_openai_subwords_for_words,
    format_with_subwords_csv,
)
from lib.input.chinese.grammar import (
    call_openai_for_grammar,
    write_parsed_grammar_csv,
)
from lib.input.chinese.processing import (
    process_file,
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
]
