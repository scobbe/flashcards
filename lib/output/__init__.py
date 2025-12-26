"""Output generation library for flashcard generation.

This package handles written mode (with etymology and Wiktionary).
For oral mode, use the lib.output.oral subpackage.
"""

from lib.output.schema_utils import (
    _field_name_to_key,
    _build_back_json_shape,
    _collect_guidelines,
    _required_optional_keys,
)
from lib.output.html import (
    fetch_wiktionary_html_status,
    wiktionary_url_for_word,
    sanitize_html,
    section_header,
    save_html_with_parsed,
    load_html_for_api,
)
from lib.output.etymology import (
    extract_back_fields_from_html,
    _etymology_complete,
    _collect_components_from_back,
    _parse_component_english_map,
    _parse_component_forms_map,
    RADICAL_VARIANT_TO_PRIMARY,
    _map_radical_variant_to_primary,
)
from lib.output.cards import (
    write_simple_card_md,
    read_parsed_input,
    render_grammar_folder,
)
from lib.output.components import (
    _generate_component_subtree,
    _get_cached_back_for_char,
    _set_cached_back_for_char,
)
from lib.output.processing import (
    _process_single_row_written,
    process_folder_written,
)

# Oral mode exports (for convenience)
from lib.output.oral import (
    write_oral_card_md,
    process_oral_row,
    process_oral_folder,
)

__all__ = [
    # schema_utils
    "_field_name_to_key",
    "_build_back_json_shape",
    "_collect_guidelines",
    "_required_optional_keys",
    # html
    "fetch_wiktionary_html_status",
    "wiktionary_url_for_word",
    "sanitize_html",
    "section_header",
    "save_html_with_parsed",
    "load_html_for_api",
    # etymology
    "extract_back_fields_from_html",
    "_etymology_complete",
    "_collect_components_from_back",
    "_parse_component_english_map",
    "_parse_component_forms_map",
    "RADICAL_VARIANT_TO_PRIMARY",
    "_map_radical_variant_to_primary",
    # cards (written mode)
    "write_simple_card_md",
    "read_parsed_input",
    "render_grammar_folder",
    # components
    "_generate_component_subtree",
    "_get_cached_back_for_char",
    "_set_cached_back_for_char",
    # processing (written mode)
    "_process_single_row_written",
    "process_folder_written",
    # oral mode
    "write_oral_card_md",
    "process_oral_row",
    "process_oral_folder",
]
