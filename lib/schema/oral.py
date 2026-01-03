"""Oral practice card schema.

Simplified card format for oral/listening practice:
- Front: Chinese characters only (simplified with traditional in parentheses)
- Back: Pinyin, English definition, and etymology
- No Wiktionary data
"""

from lib.schema.base import CardField, CardSchema


# Front side for oral cards: Chinese characters only
ORAL_FRONT_SCHEMA = CardSchema(
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
        CardField(
            name="relation",
            required=False,
            description=(
                "Optional relation indicator (e.g., 'sub-word'). If this is a sub-word, "
                "show the parent word's Chinese characters below."
            ),
        ),
        CardField(
            name="parent_chinese",
            required=False,
            description=(
                "For sub-words: the parent word in Chinese characters. "
                "Format: simplified(traditional) if different."
            ),
        ),
    ],
)


# Back side for oral cards: Pinyin, definition, and etymology (no Wiktionary data)
ORAL_BACK_SCHEMA = CardSchema(
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
            name="etymology",
            required=False,
            description=(
                "Etymology explanation. For one-character words: explain roughly why the character "
                "is formed that way (e.g., pictographic origin, semantic components). "
                "For multi-character words: explain why that combination of characters means the actual word "
                "(e.g., how the component characters combine to create the meaning)."
            ),
            field_type="line",
        ),
    ],
)


__all__ = [
    "ORAL_FRONT_SCHEMA",
    "ORAL_BACK_SCHEMA",
]

