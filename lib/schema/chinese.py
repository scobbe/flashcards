"""Chinese flashcard schemas - source of truth for AI prompts and display formatting."""

from typing import List

from lib.schema.base import (
    PromptField,
    DisplayField,
    generate_system_prompt as _generate_system_prompt,
    format_field_for_display as _format_field_for_display,
    get_display_field as _get_display_field,
    get_display_order as _get_display_order,
    extract_response_fields as _extract_response_fields,
    get_required_field_names as _get_required_field_names,
)


# =============================================================================
# Prompt Schema - Controls what we ask the AI for
# =============================================================================

def _join(lines: List[str]) -> str:
    """Join prompt lines with newlines, prefixing non-first lines with '- '."""
    if not lines:
        return ""
    result = [lines[0]]
    for line in lines[1:]:
        result.append(f"- {line}")
    return "\n".join(result)


# Reusable format instructions
CHAR_REF_FORMAT = '简(繁) (pinyin, "def"), e.g. 说(說) (shuō, "speak")'
CHAR_REF_RULE = f"EVERY Chinese character reference (except the current char) MUST use format {CHAR_REF_FORMAT} - NEVER write bare characters"
LENGTH_RULE = "1-2 sentences MAX"

CLAUSE_TRAD_RULE = [
    'MANDATORY FORMAT: simplified_clause(traditional_clause)punctuation',
    'CORRECT: 我有银子(我有銀子)，想买东西(想買東西)。',
    'CORRECT: 买银子(買銀子)。',
    'WRONG: 买银子。(買銀子。) - NEVER put punctuation inside parens',
    'WRONG: 米是粮食。(米是糧食。) - this format is FORBIDDEN',
    'Traditional in parens must be FULL sentence: 我吃饭(我吃飯)。 NOT 我吃饭(吃飯)。',
    'Pinyin must be romanization ONLY - no Chinese characters in pinyin field',
]

EXAMPLE_SENTENCE_RULES = [
    *CLAUSE_TRAD_RULE,
    "If in_contemporary_usage is false, use names/places/literary references",
]

CHINESE_PROMPT_PREAMBLE = {
    "single_char": "Chinese character etymology expert. Respond in English ONLY - no Chinese text except in character references like 說(說). NEVER include Old Chinese (OC) phonetic reconstructions like '(OC *xxx)' or 'OC *ɡroːd' anywhere in output.",
    "multi_char": "Chinese word etymology expert. Respond in English ONLY - no Chinese text except in character references like 說(說). NEVER include Old Chinese (OC) phonetic reconstructions like '(OC *xxx)' anywhere in output.",
}

# -----------------------------------------------------------------------------
# Prompt fields with inline dictionary definitions
# -----------------------------------------------------------------------------

CHINESE_PROMPT_FIELDS = [
    PromptField(
        name="traditional",
        prompt={
            "single_char": _join([
                "The traditional Chinese form of this character.",
            ]),
            "multi_char": _join([
                "The traditional Chinese form of this word.",
            ]),
        },
        response_type="string",
    ),
    PromptField(
        name="type",
        prompt={
            "single_char": "COPY type from Wiktionary in English ONLY - no Chinese (e.g. 'phono-semantic compound', 'pictogram', 'ideogrammic compound') NOT 'Pictogram ( 象形 )'",
            "multi_char": '"compound word"',
        },
        response_type="string",
    ),
    PromptField(
        name="description",
        prompt={
            "single_char": _join([
                "SHORT FORMULA ONLY - no verbose explanations",
                CHAR_REF_RULE,
                "NEVER include Old Chinese (OC) reconstructions like '(OC *xxx)' in output",
                "For PICTOGRAMS: 'Depicts X'",
                'E.g. 日(日) (rì, "sun") depicts the sun',
                'E.g. 水(水) (shuǐ, "water") depicts flowing water',
                'For COMPOUNDS: "A (meaning) + B (meaning) = intuitive explanation -> final meaning"',
                'E.g. 人(人) (rén, "person") + 木(木) (mù, "tree") = person leaning against tree -> rest',
                'E.g. 日(日) (rì, "sun") + 月(月) (yuè, "moon") = sun and moon together -> bright',
                'E.g. 女(女) (nǚ, "woman") + 子(子) (zǐ, "child") = woman with child -> good',
                'E.g. semantic: 氵(氵) (shuǐ, "water") + phonetic: 青(青) (qīng) = clear water -> clear',
                'For REDUCED/RELATED FORMS: "Reduced/related form of X" where X is the original char with format',
                'E.g. 云(雲) (yún) = reduced form of 雲(雲) (yún, "cloud")',
                'E.g. 从(從) (cóng) = reduced form of 從(從) (cóng, "follow")',
                "MUST use EXACTLY the parts from 'parts' field",
            ]),
            "multi_char": _join([
                CHAR_REF_RULE,
                "Simple formula using MORPHEMES (not individual chars).",
                'E.g. 图书(圖書) (túshū, "books") + 馆(館) (guǎn, "building") = place for books -> library',
                "MUST use EXACTLY the parts from 'parts' field",
                "NOT individual characters like 图 + 书 + 馆",
            ]),
        },
        response_type="string",
    ),
    PromptField(
        name="interpretation",
        prompt={
            "single_char": _join([
                LENGTH_RULE,
                CHAR_REF_RULE,
                "NEVER include Old Chinese (OC) reconstructions like '(OC *xxx)' in output",
                "Explain WHY the components from 'parts' field make intuitive sense together",
                'For borrowings: e.g. 其(其) (qí, "his") was originally a basket pictogram, borrowed for the pronoun; 箕(箕) (jī, "basket") added 竹(竹) (zhú, "bamboo") to reclaim the basket meaning',
                "For compounds: explain why the semantic + phonetic combination makes sense",
                "ONLY reference components listed in 'parts' field",
                "FORBIDDEN: claims about ancient beliefs, heavenly origins, or mystical symbolism",
                "No unexplained leaps like 'by extension...'",
                "No jargon",
                "Do NOT just restate the description - add insight",
            ]),
            "multi_char": _join([
                LENGTH_RULE,
                CHAR_REF_RULE,
                "Explain WHY this combination makes sense",
                'E.g. A 馆(館) (guǎn, "building") for 图书(圖書) (túshū, "books") is where you go to read and borrow them.',
                "No unexplained leaps like 'by extension...' - if you can't explain the connection, don't mention it",
                "No generic explanations like 'Chinese often...'",
                "No jargon",
                "Do NOT restate the description formula",
            ]),
        },
        response_type="string",
    ),
    PromptField(
        name="simplification",
        prompt={
            "single_char": _join([
                LENGTH_RULE,
                "Explain the SPECIFIC historical process - NOT generic 'for ease of writing'",
                "Was it: a cursive shorthand? a sound-alike? a meaning-based replacement?",
                "E.g. 鄰→邻: '令 replaced 粦 as a simpler phonetic - both sound similar (lín/lìng)'",
                "E.g. 淚→泪: '目 (eye) replaced 戾 for semantic clarity - tears come from eyes'",
                "E.g. 鳳→凤: '又 is a cursive shorthand for the bird radical - unrelated to sound or meaning'",
                "NEVER say 'simplified for ease' without explaining HOW (cursive? phonetic? semantic?)",
                'Or "none" if traditional = simplified',
            ]),
            "multi_char": "none",
        },
        response_type="string",
        none_value="none",
    ),
    PromptField(
        name="parts",
        prompt={
            "single_char": _join([
                "Array of component chars [{char, trad, pinyin, english}].",
                "COPY-PASTE the exact characters from Wiktionary text - do NOT invent or guess",
                "If Wiktionary is not provided, return empty array",
                "If Wiktionary says '氵+ 可', use exactly 氵and 可 - not similar-looking variants",
                "If Wiktionary says 'reduced form of X', list X as a part",
                "NEVER invent or guess characters - only use what appears in Wiktionary",
                "For PICTOGRAMS: return empty array",
                'E.g. 豉 with Wiktionary "semantic 豆 + phonetic 支" → parts: 豆(豆) (dòu, "bean"), 支(支) (zhī, "branch")',
            ]),
            "multi_char": _join([
                "Array of MORPHEME breakdown [{char, trad, pinyin, english}].",
                "Split into meaningful subwords, NOT individual characters",
                "E.g. 图书馆 → [图书, 馆] not [图, 书, 馆]",
                "E.g. 电影明星 → [电影, 明星] not [电, 影, 明, 星]",
                "Each part: pinyin with tone marks, up to 4 meanings separated by '; ' (semicolon + space)",
            ]),
        },
        response_type="list",
    ),
    PromptField(
        name="in_contemporary_usage",
        prompt=_join([
            "Boolean.",
            "true if commonly used in modern Chinese (news, daily conversation, textbooks)",
            "false if archaic, literary-only, rare variant, or only appears in names/places",
        ]),
        response_type="boolean",
    ),
    PromptField(
        name="examples",
        prompt={
            "single_char": _join([
                "Array of 2-3 sentences [{chinese, pinyin, english}].",
                *EXAMPLE_SENTENCE_RULES,
            ]),
            "multi_char": _join([
                "Array of 2-3 sentences [{chinese, pinyin, english}].",
                *EXAMPLE_SENTENCE_RULES,
            ]),
        },
        response_type="list",
        max_items=3,
    ),
]


def generate_system_prompt(variant: str) -> str:
    """Generate the system prompt for Chinese card generation."""
    return _generate_system_prompt(CHINESE_PROMPT_PREAMBLE, CHINESE_PROMPT_FIELDS, variant)


def extract_response_fields(response_data: dict) -> dict:
    """Extract and normalize AI response fields based on schema."""
    return _extract_response_fields(CHINESE_PROMPT_FIELDS, response_data)


def get_required_field_names() -> List[str]:
    """Get list of required field names for cache validation."""
    return _get_required_field_names(CHINESE_PROMPT_FIELDS)


def extract_to_cache_format(
    response_data: dict,
    simplified: str,
    pinyin: str,
    english: str,
) -> dict:
    """Extract AI response and transform to cache format.

    The cache format groups type/interpretation/simplification into an etymology dict,
    while the AI returns them as flat fields.

    Args:
        response_data: Raw AI response
        simplified: Input simplified form
        pinyin: Input pinyin
        english: Input english definition

    Returns:
        Dict ready for cache storage
    """
    fields = extract_response_fields(response_data)

    # Handle simplification none_value
    simplification = fields.get("simplification", "")
    if simplification.lower() == "none":
        simplification = ""

    cache_data = {
        "simplified": simplified,
        "traditional": fields.get("traditional", simplified),
        "pinyin": pinyin,
        "english": english,
        "etymology": {
            "type": fields.get("type", ""),
            "description": fields.get("description", ""),
            "interpretation": fields.get("interpretation", ""),
            "simplification": simplification,
        },
        "parts": fields.get("parts", []),
        "in_contemporary_usage": fields.get("in_contemporary_usage", True),
        "examples": fields.get("examples", []),
    }
    return cache_data


def extract_from_cache(cached_data: dict) -> dict:
    """Extract fields from cached data back to working format.

    Returns a dict with: etymology, traditional, parts, examples, in_contemporary_usage
    """
    etymology = cached_data.get("etymology", {})
    if isinstance(etymology, dict):
        etymology = {
            "type": etymology.get("type", ""),
            "description": etymology.get("description", ""),
            "interpretation": etymology.get("interpretation", ""),
            "simplification": etymology.get("simplification", ""),
        }
    else:
        etymology = {"type": "", "description": "", "interpretation": "", "simplification": ""}

    return {
        "etymology": etymology,
        "traditional": cached_data.get("traditional", cached_data.get("simplified", "")),
        "parts": cached_data.get("parts", cached_data.get("components", [])),
        "examples": cached_data.get("examples", []),
        "in_contemporary_usage": cached_data.get("in_contemporary_usage", True),
    }


# Mapping from display schema field names to cache field names
DISPLAY_TO_CACHE_FIELD = {
    "definition": "english",
    "pinyin": "pinyin",
    "components": "parts",
    "etymology": "etymology",
    "examples": "examples",
}


def is_cache_valid(cached_data: dict) -> bool:
    """Check if cached data has all required fields for a valid entry.

    Uses the display schema to determine required fields.
    """
    if not cached_data:
        return False

    # Check all display schema fields have corresponding cache data
    for display_field in CHINESE_DISPLAY_SCHEMA:
        cache_field = DISPLAY_TO_CACHE_FIELD.get(display_field.name)
        if cache_field and cache_field not in cached_data:
            return False

    # Additional validation: examples must be non-empty
    if not cached_data.get("examples"):
        return False

    # Additional validation: traditional must be set
    if "traditional" not in cached_data:
        return False

    # Additional validation: etymology must have required subfields
    etymology = cached_data.get("etymology", {})
    if not isinstance(etymology, dict):
        return False

    return True


# =============================================================================
# Display Schema - Controls how we render the card markdown
# =============================================================================

CHINESE_DISPLAY_SCHEMA = [
    DisplayField(name="definition", label="definition", field_type="line"),
    DisplayField(name="pinyin", label="pinyin", field_type="line"),
    DisplayField(name="components", label="components", field_type="nested",
                 children=["pinyin", "english"]),
    DisplayField(name="etymology", label="etymology", field_type="nested_labeled",
                 children=["type", "description", "interpretation", "simplification"]),
    DisplayField(name="examples", label="examples", field_type="nested",
                 children=["pinyin", "english"]),
]


def format_field_for_display(field_name: str, value, indent: int = 0) -> List[str]:
    """Format a field value for markdown display."""
    return _format_field_for_display(CHINESE_DISPLAY_SCHEMA, field_name, value, indent)


def get_display_field(name: str):
    """Get a display field by name."""
    return _get_display_field(CHINESE_DISPLAY_SCHEMA, name)


def get_display_order() -> List[str]:
    """Get the display field order."""
    return _get_display_order(CHINESE_DISPLAY_SCHEMA)


__all__ = [
    # Prompt schema
    "CHINESE_PROMPT_PREAMBLE",
    "CHINESE_PROMPT_FIELDS",
    "generate_system_prompt",
    "extract_response_fields",
    "get_required_field_names",
    # Cache helpers
    "extract_to_cache_format",
    "extract_from_cache",
    "is_cache_valid",
    "DISPLAY_TO_CACHE_FIELD",
    # Display schema
    "CHINESE_DISPLAY_SCHEMA",
    "format_field_for_display",
    "get_display_field",
    "get_display_order",
]
