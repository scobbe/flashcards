"""Full card schema with etymology and all fields.

Used for comprehensive flashcards with Wiktionary data.
"""

from lib.schema.base import CardField, CardSchema


# Front side schema (content before FRONT_BACK_DIVIDER)
FRONT_SCHEMA = CardSchema(
    name="front",
    fields=[
        CardField(
            name="english",
            required=True,
            description="Short English definition/gloss for the headword.",
        ),
        CardField(
            name="subheader",
            required=False,
            description=(
                "Optional additional header on the front. Render as a third-level header (### ...). "
                "For decomposed cards, subword lines use the pattern: '### SUBWORD of \"english\"' (no angle brackets)."
            ),
        ),
    ],
)


# Back side schema (content after FRONT_BACK_DIVIDER, before CARD_DIVIDER)
BACK_SCHEMA = CardSchema(
    name="back",
    fields=[
        CardField(
            name="traditional",
            required=True,
            description="Traditional Chinese form(s) for the headword.",
            field_type="line",
        ),
        CardField(
            name="simplified",
            required=True,
            description="Simplified Chinese form(s) for the headword.",
            field_type="line",
        ),
        CardField(
            name="pronunciation",
            required=True,
            description=(
                "Pinyin with tone marks for the headword; multiple readings separated by ' / '."
            ),
            ai_prompt=(
                "From the provided Wiktionary HTML, extract the PRONUNCIATION in standard Hanyu Pinyin with DIACRITIC tone marks.\n"
                "RULES:\n"
                "- Output ONLY Pinyin (no brackets, no slashes other than separator, no Chinese).\n"
                "- Use tone marks (e.g., déi) not numbers.\n"
                "- If multiple distinct readings exist, join with ' / ' (space, slash, space).\n"
                "- Keep syllable separation with spaces; do not include parts of speech or notes."
            ),
            field_type="line",
            default_provider=lambda ctx: ctx.get("pinyin", ""),
        ),
        CardField(
            name="definition",
            required=True,
            description="Repeat of the English definition shown on the front side.",
            field_type="line",
        ),
        CardField(
            name="contemporary usage",
            required=True,
            description=(
                "Short sublist of example phrases/compounds for the relevant modern sense (from input HTML primarily). "
                "Items MUST be multi-character (no single-character items)."
            ),
            ai_prompt=(
                "From the provided Wiktionary HTML only, output a short sublist of example PHRASES or COMPOUND VOCAB WORDS for the relevant modern sense.\n"
                "STRICT FORMAT RULES:\n"
                "- Each line MUST start with '- ' (dash and space).\n"
                "- Each line MUST be: CJK phrase (pinyin, \"english\").\n"
                "- Do NOT use angle brackets around Chinese, pinyin, or English.\n"
                "- The CJK phrase MUST be at least TWO characters long (no single-character items).\n"
                "- pinyin MUST use diacritical tone marks (e.g., hǎo), do NOT use tone numbers.\n"
                "- CHINESE phrase: write in SIMPLIFIED characters; ASCII parentheses are allowed for annotations. No Latin letters.\n"
                "- HARD RULE: For EVERY Simplified character in the phrase that has a DISTINCT Traditional form, INSERT its Traditional character in ASCII parentheses IMMEDIATELY after that character (no spaces). Example: 宝贝 → 宝(寶)贝(貝). Do NOT annotate characters where Simplified == Traditional.\n"
                "- English: concise phrase (2–8 words) in double quotes, no trailing period.\n"
                "- No extra text, labels, or headers.\n"
                "- Output EXACTLY 4 items.\n"
                "- PRIORITY: If a context phrase is provided in the input, use it as the basis for the FIRST example (matching its usage context), then provide 3 additional varied examples.\n"
                "HEADWORD MATCHING (H):\n"
                "- Let H be the exact headword string.\n"
                "- If len(H) == 1 (single character): each CJK phrase MUST be a common modern compound or phrase CONTAINING H (preferably starting with H), and MUST be length >= 2. Do NOT output H alone.\n"
                "- If len(H) > 1 (multi-character): each CJK phrase MUST begin with H and represent common modern compounds/phrases formed from H; ensure length >= len(H) + 1.\n"
                "SOURCES WITHIN HTML (in priority order):\n"
                "1) Usage examples (including glossed examples) under the target sense.\n"
                "2) Compounds/Derived terms that are in common/modern use.\n"
                "3) Phrases in Definitions/Notes clearly used in modern contexts.\n"
                "IMPORTANT:\n"
                "- Prefer modern/common items; avoid archaic/obsolete/classical when alternatives exist.\n"
                "- If fewer than 4 suitable items are present in the HTML, supplement using general knowledge consistent with the entry's modern senses to reach 4.\n"
                "- If the entry is truly not in contemporary use, output exactly: None, not in contemporary use."
            ),
            field_type="sublist",
            max_items=4,
            empty_fallback="None, not in contemporary use",
        ),
        CardField(
            name="etymology ({traditional})",
            required=True,
            description=(
                "Concise etymology for the Traditional form. Includes type, a simple description, a plain-language "
                "interpretation, a reference link, and (optionally) the simplification rule."
            ),
            field_type="section",
            children=[
                CardField(
                    name="type",
                    required=True,
                    description=(
                        "One of the standard character formation types, or a short progression if it changed over time (English only; no Chinese characters)."
                    ),
                    ai_prompt=(
                        "Rely primarily on the provided Wiktionary HTML. Output the formation TYPE in ENGLISH ONLY (e.g., pictogram, ideogram, ideogrammic compound, phono-semantic compound, semantic compound).\n"
                        "STRICT FORMAT RULES:\n"
                        "- Return a SINGLE label or an ARROW-SEPARATED progression only (e.g., pictogram → phono-semantic compound).\n"
                        "- Do NOT use plus signs (+) or slashes (/).\n"
                        "- Do NOT include parentheses or any Chinese, Pinyin, or transliteration (e.g., no 'jiajie').\n"
                        "- Use only ASCII letters, spaces, and hyphens.\n"
                        "Use general reasoning only if the HTML is insufficient."
                    ),
                    field_type="line",
                ),
                CardField(
                    name="description",
                    required=True,
                    description=(
                        "VERY concise arrow sequence A → B → C that shows the formation flow. HARD RULE: EVERY Chinese element MUST be rendered as Simplified(Traditional) (pinyin, \"english\"); omit (Traditional) if identical. Do NOT use angle brackets."
                    ),
                    ai_prompt=(
                        "Rely primarily on the provided Wiktionary HTML. Output a SINGLE LINE arrow sequence (A → B → C…) that shows the formation flow.\n"
                        "STRICT FORMAT RULES:\n"
                        "- Use terse tokens like: pictogram of Simplified(Traditional) (pinyin, \"english\"), semantic: Simplified(Traditional) (pinyin, \"english\"), phonetic: Simplified(Traditional) (pinyin, \"english\"), ideogrammic: Simplified(Traditional) (pinyin, \"english\") + Simplified(Traditional) (pinyin, \"english\").\n"
                        "- HARD RULE: EVERY Chinese element MUST be rendered as Simplified(Traditional) (pinyin, \"english\"); omit (Traditional) if identical. Use Simplified as the base form. Do NOT use angle brackets.\n"
                        "- Do NOT mention where a component appears elsewhere (e.g., 'appears as the top of 灰'); describe ONLY the formation path of the head character.\n"
                        "- Include ONLY the core historical formation events; EXCLUDE script/graphic variants, orthographic regularizations, and other side notes unrelated to the core formation.\n"
                        "- If the TYPE is pictogram, you MUST explicitly state what it depicts (e.g., 'pictogram: depiction of calyx of a flower'), not an abstract concept.\n"
                        "- END THE LINE WITH A PERIOD.\n"
                        "Use general reasoning only if the HTML is insufficient."
                    ),
                    field_type="line",
                ),
                CardField(
                    name="interpretation",
                    required=True,
                    description=(
                        "Simple, intuitive explanation of how A → B → C flows; avoid scholarly tone and jargon."
                    ),
                    ai_prompt=(
                        "Rely primarily on the provided Wiktionary HTML. In 2–3 short sentences, explain in plain, accurate terms how A → B → C flows and why changes happened.\n"
                        "HARD RULES:\n"
                        "- If the TYPE is pictogram, FIRST name the concrete thing depicted (e.g., 'depicts the calyx of a flower'), THEN describe later semantic shifts (e.g., borrowing/extension via compositions like 否 leading to 'no/negation'), making clear which is original vs later.\n"
                        "- Do NOT claim a pictogram 'represents the idea of' an abstract notion; describe the depiction explicitly instead.\n"
                        "- If credible alternative interpretations are mentioned in the HTML (e.g., Shuowen, Karlgren, Wieger), briefly note them as alternatives.\n"
                        "- If you reference specific components, render Chinese as Simplified(Traditional) (pinyin, \"english\") without angle brackets; omit (Traditional) if identical. Use Simplified as the base form.\n"
                        "- Do NOT discuss where the components appear in other characters; restrict to the head character's formation and meaning.\n"
                        "- Critically: explain WHY the SEMANTIC component applies to the MODERN meaning(s). If phono-semantic, explicitly identify the semantic determinative vs the phonetic, and state how the semantic determinative matches the word's domain today. If semantic/ideogrammic, state how the parts combine to yield the current sense. If meaning was borrowed/extended, explain the mechanism and why that newer sense persisted.\n"
                        "- Be concise and factual. END WITH A PERIOD. Use general reasoning only as a last resort."
                    ),
                    field_type="line",
                ),
                CardField(
                    name="component characters",
                    required=False,
                    description=(
                        "List ALL UNIQUE single Chinese characters that appear in the etymology description field; EXCLUDE the headword itself; deduplicate and preserve description order."
                    ),
                    ai_prompt=(
                        "From the etymology.description STRING YOU OUTPUT, list every UNIQUE SINGLE Chinese CHARACTER that appears anywhere in that description, in order of FIRST appearance.\n"
                        "STRICT FORMAT RULES:\n"
                        "- Output a short list, one item per line, each item starting with '- '.\n"
                        "- HARD RULE: Each item MUST be formatted as: Simplified(Traditional) (pinyin, \"english\"); if Traditional == Simplified, write only Simplified without parentheses. Use diacritic tone marks for pinyin. Keep English gloss concise (1–3 words).\n"
                        "- Deduplicate; preserve the order they first appear in the DESCRIPTION string.\n"
                        "- Do not infer or add characters not present in the description.\n"
                        "- EXCLUDE the HEADWORD character itself if it appears (do not include the card's own character)."
                    ),
                    field_type="sublist",
                    max_items=12,
                    empty_fallback="None, character is in atomic form",
                ),
                CardField(
                    name="reference",
                    required=True,
                    description="Reference URL to the relevant Wiktionary page section.",
                    field_type="line",
                    default_provider=lambda ctx: ctx.get("wiktionary_url", ""),
                ),
                CardField(
                    name="simplification rule ({simplified})",
                    required=False,
                    description=(
                        "Explain the rule and intuition for the simplification from Traditional to Simplified for this character."
                    ),
                    ai_prompt=(
                        "Using only the provided HTML and general knowledge of Chinese simplification, explain briefly why "
                        "this simplified form was adopted (e.g., component replacement, stroke reduction, graphic regularization). END WITH A PERIOD."
                    ),
                    field_type="line",
                    skip_if=lambda ctx: (ctx.get("traditional") or "") == (ctx.get("simplified") or ""),
                ),
            ],
        ),
    ],
)


__all__ = [
    "FRONT_SCHEMA",
    "BACK_SCHEMA",
]

