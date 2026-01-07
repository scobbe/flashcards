"""Unified Chinese flashcard schema.

Single schema for all Chinese flashcards:
- Front: Chinese characters (simplified with traditional in parentheses)
- Back: Pinyin, English definition, character breakdown, etymology, examples
"""

from lib.schema.base import CardField, CardSchema


# Front side schema: Chinese characters only
CHINESE_FRONT_SCHEMA = CardSchema(
    name="front",
    fields=[
        CardField(
            name="chinese",
            required=True,
            description=(
                "Chinese characters for the headword. Format: simplified(traditional) if different, "
                "otherwise just simplified. No pinyin on the front."
            ),
        ),
    ],
)


# Back side schema: Pinyin, definition, characters, etymology, examples
CHINESE_BACK_SCHEMA = CardSchema(
    name="back",
    fields=[
        CardField(
            name="pinyin",
            required=True,
            description="Pinyin with tone marks for the headword.",
            field_type="line",
        ),
        CardField(
            name="definition",
            required=True,
            description="English definition/gloss for the headword.",
            field_type="line",
        ),
        CardField(
            name="characters",
            required=False,
            description=(
                "For multi-character words: breakdown of each character with its pinyin and meaning."
            ),
            field_type="sublist",
        ),
        CardField(
            name="etymology",
            required=False,
            description=(
                "Etymology explanation with structured sub-fields:\n"
                "  - type: Formation type (pictogram, ideogram, phono-semantic compound, etc.)\n"
                "  - description: Brief formation description (e.g., 'semantic: X + phonetic: Y')\n"
                "  - interpretation: 2-3 sentence plain-language explanation of why/how"
            ),
            field_type="structured",
            children=[
                CardField(name="type", required=True, description="Formation type: pictogram, ideogram, ideogrammic compound, phono-semantic compound, semantic compound, or compound word"),
                CardField(name="description", required=True, description="Brief formation description"),
                CardField(name="interpretation", required=True, description="2-3 sentence plain explanation"),
            ],
        ),
        CardField(
            name="components",
            required=False,
            description=(
                "For single characters with recursive=True: list of component characters that make up "
                "this character, each with their own pinyin, definition, and etymology."
            ),
            field_type="sublist",
        ),
        CardField(
            name="examples",
            required=False,
            description="Example sentences demonstrating usage.",
            field_type="sublist",
        ),
    ],
)


__all__ = [
    "CHINESE_FRONT_SCHEMA",
    "CHINESE_BACK_SCHEMA",
]
