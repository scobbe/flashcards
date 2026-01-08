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
# Format: 简(繁) SPACE (pinyin, "def") - note the REQUIRED space between 简(繁) and (pinyin, "def")
CHAR_REF_FORMAT = '简(繁) (pinyin, "def") with REQUIRED SPACE before the pinyin parenthetical'
CHAR_REF_RULE = (
    "ALL character references MUST use this EXACT format: 简(繁) (pinyin, \"def\")\n"
    "- REQUIRED: 简(繁) with traditional in parentheses\n"
    "- REQUIRED: space between 简(繁) and (pinyin, \"def\")\n"
    "- REQUIRED: pinyin with tone marks\n"
    "- REQUIRED: double quotes around definition, NEVER single quotes\n"
    "- REQUIRED: applies to EVERY character mentioned, no exceptions\n"
    "- CORRECT: 士(士) (shì, \"scholar\"), 呂(呂) (lǚ, \"spine\")\n"
    "- CORRECT: 说(說) (shuō, \"speak\"), 人(人) (rén, \"person\")\n"
    "- WRONG: 士 (\"scholar\") - missing 士(士) and pinyin\n"
    "- WRONG: 说(說)(shuō, \"speak\") - missing space\n"
    "- WRONG: 说(說) (shuō, 'speak') - single quotes\n"
    "- WRONG: 说 or 說 alone - bare characters forbidden"
)
LENGTH_RULE = "1-2 sentences MAX"

CLAUSE_TRAD_RULE = [
    'REQUIRED FORMAT: Each clause gets (traditional) immediately after, then punctuation',
    'Traditional form in parentheses is MANDATORY - never omit it',
    'For single clause: simplified(traditional)punctuation',
    'For comma sentences: clause1(trad1)，clause2(trad2)。',
    'CORRECT: 银色是一种优雅的颜色(銀色是一種優雅的顏色)。',
    'CORRECT: 我有银子(我有銀子)，想买东西(想買東西)。',
    'CORRECT: 春天到来时(春天到來時)，麦田变得金黄(麥田變得金黃)。',
    'WRONG: 春天到来时，麦田变得金黄(春天到來時，麥田變得金黃)。 - trad at end instead of after each clause',
    'WRONG: 银色是一种优雅的颜色。 - MISSING traditional form',
    'Pinyin must be romanization ONLY - no Chinese characters',
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
                "SHORT FORMULA showing the character's evolutionary history through its components",
                "ALL TEXT MUST BE IN ENGLISH - no Chinese except in character references like 欣(欣)",
                CHAR_REF_RULE,
                "NEVER include Old Chinese (OC) reconstructions like '(OC *xxx)' in output",
                "Show progression using ARROWS: original components -> intermediate meaning -> later additions -> final form",
                "Use ARROWS (->) to separate each step, NOT semicolons",
                "For PICTOGRAMS: 'Depicts X' - include ONLY directly related characters (derived from, derived to, stylized as, original form of) - EXCLUDE 'compare to' and 'similar to' contrasts",
                "PREFER scholarly etymology over folk/traditional explanations - if Wiktionary says 'traditionally explained as X' but 'disputed' or gives another primary explanation, use the PRIMARY one",
                'E.g. 西 = bag/basket borrowed for phonetic value (NOT the disputed folk etymology of bird in nest)',
                'E.g. 日(日) (rì, "sun") depicts the sun',
                'E.g. 水(水) (shuǐ, "water") depicts flowing water',
                'E.g. 易(易) depicts a filled container (original form of 賜(賜) (cì, "bestow")) -> borrowed phonetically for "easy"',
                'For COMPOUNDS: "A (meaning) + B (meaning) = explanation -> final meaning"',
                'E.g. 人(人) (rén, "person") + 木(木) (mù, "tree") = person leaning against tree -> rest',
                'E.g. semantic: 氵(氵) (shuǐ, "water") + phonetic: 青(青) (qīng) = clear water -> clear',
                'For COMPOUNDS with evolution in Wiktionary: show how character developed through stages',
                'E.g. 貝(貝) (bèi, "cowry") + 又(又) (yòu, "hand") -> obtaining valuables -> 彳(彳) (chì, "step") added, 又 changed to 寸(寸) (cùn, "inch"), 貝 corrupted to 旦(旦) (dàn, "dawn") -> final form 得',
                'For ANCIENT/RELATED FORMS: show historical relationship to contemporary form',
                'E.g. 䰜(䰜) (lì, "cauldron") is an ancient form of 鬲(鬲) (lì, "cauldron"), both depict a cooking vessel, diverged over time',
                "Include ALL components from Wiktionary that explain the character's development",
                "MUST use EXACTLY ALL parts from 'parts' field - don't omit any",
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
                "Include FACTUAL context when relevant - cite classical texts or historical records, not speculation",
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
                "Include FACTUAL historical/philosophical context when relevant (Confucianism, Buddhism, classical texts)",
                'E.g. 大同(大同) (dàtóng, "Great Unity") is a Confucian utopian ideal from the Book of Rites (禮記/礼记)',
                "No unexplained leaps like 'by extension...' - if you can't explain the connection, don't mention it",
                "No generic explanations like 'Chinese often...'",
                "No speculation about ancient beliefs - only cite verifiable sources (classical texts, historical records)",
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
                'Return EMPTY STRING "" if traditional = simplified (no simplification exists)',
                "Otherwise explain the SPECIFIC historical process - NOT generic 'for ease of writing'",
                LENGTH_RULE,
                CHAR_REF_RULE,
                "Was it: a cursive shorthand? a sound-alike? a meaning-based replacement?",
                "E.g. 鄰(鄰)→邻(鄰): 令(令) (lìng, \"order\") replaced 粦(粦) (lín, \"fire\") as a simpler phonetic",
                "E.g. 淚(淚)→泪(淚): 目(目) (mù, \"eye\") replaced 戾(戾) (lì, \"oppose\") for semantic clarity",
                "E.g. 鳳(鳳)→凤(鳳): 又(又) (yòu, \"again\") is a cursive shorthand for the bird radical",
                "NEVER say 'simplified for ease' without explaining HOW (cursive? phonetic? semantic?)",
            ]),
            "multi_char": '""',
        },
        response_type="string",
        none_value="",
    ),
    PromptField(
        name="parts",
        prompt={
            "single_char": _join([
                "Array of ALL OTHER characters referenced in YOUR description AND interpretation fields [{char, trad, pinyin, english}].",
                "ONLY include characters that YOU wrote in description/interpretation - nothing else",
                "IGNORE self-references (don't include the character itself in parts)",
                "Use Wiktionary as PRIMARY SOURCE for component information.",
                "If Wiktionary says '氵+ 可', use exactly 氵and 可 - not similar-looking variants",
                "EMPTY ARRAY ONLY FOR: Pure pictograms where description/interpretation mention NO other characters (日, 月, 山, 水, 火, 木)",
                "NON-EMPTY FOR: ideogrammic compounds, phono-semantic compounds, ANY character with 2+ components",
                "NON-EMPTY FOR: Pictograms with directly related characters (derived from, derived to, stylized as, original form of) - EXCLUDE 'compare to' contrasts",
                'E.g. 易 = pictogram, description mentions 賜, so parts = [{char: "賜", trad: "賜", pinyin: "cì", english: "bestow"}]',
                'E.g. 全 = ideogrammic compound (入 + 玉), so parts = [入, 玉]',
                'E.g. 欣 = phono-semantic compound (斤 + 欠), so parts = [斤, 欠]',
                "CRITICAL: If your description/interpretation mentions 'stylized as X', 'derived to X', 'original form of X', 'derivative X' -> X MUST be in parts",
                "RULE: parts = ALL directly related characters from YOUR description/interpretation - EXCLUDE 'compare to' contrasts only",
            ]),
            "multi_char": _join([
                "Array of MORPHEME breakdown [{char, trad, pinyin, english}].",
                "Use your knowledge of Chinese to split into meaningful morphemes.",
                "NEVER return the whole word as a single part - ALWAYS break it down.",
                "For 2-char words: usually split into 2 individual characters.",
                "For 3+ char words: split into meaningful morphemes (may be 1, 2, or 3 chars each).",
                "Keep compound words together when they form a single meaning unit.",
                "E.g. 燕麦粥 → [燕麦, 粥] because 燕麦='oats' is one lexical unit",
                "E.g. 大同区 → [大同, 区] because 大同='Great Unity' is a Confucian concept and place name",
                "E.g. 图书馆 → [图书, 馆] because 图书='books' is one unit",
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
                "chinese field MUST have format: simplified(traditional)punctuation",
                "E.g. chinese: \"银色是一种优雅的颜色(銀色是一種優雅的顏色)。\"",
                "E.g. chinese: \"我有银子(我有銀子)，想买东西(想買東西)。\"",
                "WRONG: \"银色是一种优雅的颜色。\" - missing traditional",
                *EXAMPLE_SENTENCE_RULES,
            ]),
            "multi_char": _join([
                "Array of 2-3 sentences [{chinese, pinyin, english}].",
                "chinese field MUST have format: simplified(traditional)punctuation",
                "E.g. chinese: \"我们说话(我們說話)。\"",
                "E.g. chinese: \"人口增长很快(人口增長很快)。\"",
                "WRONG: \"我们说话。\" - missing traditional",
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


def generate_system_prompt_no_examples(variant: str) -> str:
    """Generate system prompt WITHOUT examples field."""
    fields_no_examples = [f for f in CHINESE_PROMPT_FIELDS if f.name != "examples"]
    return _generate_system_prompt(CHINESE_PROMPT_PREAMBLE, fields_no_examples, variant)


def generate_examples_system_prompt(variant: str) -> str:
    """Generate system prompt for examples ONLY."""
    examples_field = next((f for f in CHINESE_PROMPT_FIELDS if f.name == "examples"), None)
    if not examples_field:
        return ""

    preamble = (
        "Chinese example sentence generator.\n"
        "FORMAT: Each clause gets its own (traditional) immediately after, then punctuation.\n"
        "For single clause: simplified(traditional)punctuation\n"
        "For comma sentences: clause1(trad1)，clause2(trad2)。\n"
        "CORRECT: \"我们在大门口等你(我們在大門口等你)。\"\n"
        "CORRECT: \"春天到来时(春天到來時)，麦田变得金黄(麥田變得金黃)。\"\n"
        "CORRECT: \"我有银子(我有銀子)，想买东西(想買東西)。\"\n"
        "WRONG: \"春天到来时，麦田变得金黄(春天到來時，麥田變得金黃)。\" - trad at end instead of after each clause\n"
        "PINYIN MUST have tone marks (ā á ǎ à, ē é ě è, etc.) - NEVER plain letters.\n"
        "CORRECT: \"Wǒ měitiān zǎochén dōu huì chī yī wǎn yànmàizhōu.\"\n"
        "WRONG: \"Wo meitian zaochen dou hui chi yi wan yanmaizhou.\""
    )
    prompt = examples_field.get_prompt(variant)
    return f"{preamble}\nReturn JSON with this field:\n- examples: {prompt}"


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
    "generate_system_prompt_no_examples",
    "generate_examples_system_prompt",
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
