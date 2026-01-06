"""English vocabulary card schema.

Simplified card format for English vocabulary study:
- Front: English word
- Back: Definition, Origin, Pronunciation (non-technical)
- No Wiktionary data, uses OpenAI for content
"""

from lib.schema.base import CardField, CardSchema


# Front side for English cards: word only
ENGLISH_FRONT_SCHEMA = CardSchema(
    name="front",
    fields=[
        CardField(
            name="word",
            required=True,
            description="The English vocabulary word to study.",
        ),
    ],
)


# Back side for English cards: definition, origin, pronunciation
ENGLISH_BACK_SCHEMA = CardSchema(
    name="back",
    fields=[
        CardField(
            name="definition",
            required=True,
            description=(
                "Concise but informative definition(s) of the word. Multiple related meanings "
                "can be listed as bullet points. Include relevant dates when applicable "
                "(birth/death dates for people, time periods for events/eras)."
            ),
            ai_prompt=(
                "Provide a clear, succinct definition of the word. If there are multiple "
                "related meanings, list each as a separate bullet point. Keep each definition "
                "to 1-2 lines. Use plain language, avoid jargon.\n\n"
                "IMPORTANT: Include relevant dates when applicable:\n"
                "- For people: include birth and death dates (e.g., '1564-1616')\n"
                "- For historical events: include the year or time period (e.g., '1776' or '14th century')\n"
                "- For eras/periods: include the date range (e.g., '1920s' or '500-1500 CE')\n\n"
                "Format as a bulleted list with '- '."
            ),
            field_type="sublist",
            max_items=3,
        ),
        CardField(
            name="etymology",
            required=True,
            description=(
                "Etymologie des Wortes: Sprachherkunft, Wurzelwörter und deren ursprüngliche "
                "Bedeutung. Wie das Wort sprachlich entstanden ist."
            ),
            ai_prompt=(
                "Provide the etymology of the word. Include:\n"
                "- The language of origin (Greek, Latin, French, German, etc.)\n"
                "- The original root word(s) and their literal meaning\n"
                "- How the word was formed or derived\n"
                "Keep it succinct (2-3 bullet points max). Focus on linguistic origins only. "
                "Format as a bulleted list with '- '."
            ),
            field_type="sublist",
            max_items=3,
        ),
        CardField(
            name="history",
            required=True,
            description=(
                "Historischer Hintergrund: relevante Daten, Zeiträume, geschichtlicher Kontext, "
                "wie sich die Bedeutung oder Verwendung des Wortes im Laufe der Zeit entwickelt hat."
            ),
            ai_prompt=(
                "Provide historical background for the word. Include:\n"
                "- Relevant dates (when it first appeared, key historical moments)\n"
                "- Historical context (what was happening when this word/concept emerged)\n"
                "- How usage or meaning evolved over time\n"
                "- Notable people, events, or periods associated with it\n"
                "Keep it succinct (2-3 bullet points max). Focus on history, not linguistics. "
                "Format as a bulleted list with '- '."
            ),
            field_type="sublist",
            max_items=3,
        ),
        CardField(
            name="pronunciation",
            required=True,
            description=(
                "Non-technical, easy-to-read pronunciation guide. Use common syllable "
                "breakdowns with capitalized stress, not IPA."
            ),
            ai_prompt=(
                "Provide a simple, non-technical pronunciation guide. Use common syllable "
                "breakdowns with CAPITALIZED stress. Example: 'kah-kis-TAH-kruh-see' for "
                "'kakistocracy'. Do NOT use IPA symbols. Make it easy for anyone to read aloud."
            ),
            field_type="line",
        ),
    ],
)


__all__ = [
    "ENGLISH_FRONT_SCHEMA",
    "ENGLISH_BACK_SCHEMA",
]

