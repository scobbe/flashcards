from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


# File-format constants
FRONT_BACK_DIVIDER: str = "---"
CARD_DIVIDER: str = "%%%"


@dataclass(frozen=True)
class CardField:
    name: str
    required: bool
    description: str
    ai_prompt: Optional[str] = None
    children: Optional[List["CardField"]] = None
    # Rendering/type metadata (schema-driven, no hardcoded key checks in generator)
    field_type: str = "line"  # one of: "line" | "sublist" | "section"
    # Optional rendering condition (callable evaluated with context dict)
    skip_if: Optional[Callable[[Dict[str, Any]], bool]] = None
    # Optional default value provider (evaluated with context dict)
    default_provider: Optional[Callable[[Dict[str, Any]], Any]] = None
    # Optional maximum items for sublist fields (enforced post-generation)
    max_items: Optional[int] = None
    # Optional fallback text if a field (esp. sublist) is empty when rendering
    empty_fallback: Optional[str] = None


@dataclass(frozen=True)
class CardSchema:
    name: str
    fields: List[CardField] = field(default_factory=list)


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
                "For decomposed cards, subword lines use the pattern: '### <subword> of \"<english>\"'."
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
            name="definition",
            required=True,
            description="Repeat of the English definition shown on the front side.",
            field_type="line",
        ),
        CardField(
            name="Contemporary usage",
            required=True,
            description=(
                "Short sublist of example phrases for the relevant sense (from input HTML only), formatted strictly as: "
                "<chinese character> (<pinyin>, \"<english>\"). Pinyin MUST use diacritical tone marks (no tone numbers). "
                "If none present, return exactly: None, not in contemporary use."
            ),
            ai_prompt=(
                "From the provided Wiktionary HTML only, output a short sublist of example phrases for the relevant sense.\n"
                "STRICT FORMAT RULES:\n"
                "- Each line MUST start with '- ' (dash and space).\n"
                "- Each line MUST be: <chinese character> (<pinyin>, \"<english>\").\n"
                "- pinyin MUST use diacritical tone marks (e.g., hǎo), do NOT use tone numbers.\n"
                "- CHINESE: only CJK characters (no Latin).\n"
                "- English: concise phrase (2–8 words) in double quotes, no trailing period.\n"
                "- No extra text, labels, or headers.\n"
                "- Output at most 3 items.\n"
                "If no examples are present, output exactly: None, not in contemporary use."
            ),
            field_type="sublist",
            max_items=3,
            empty_fallback="None, not in contemporary use",
        ),
        CardField(
            name="Etymology ({traditional})",
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
                        "Rely primarily on the provided Wiktionary HTML. Identify the formation type in ENGLISH ONLY (e.g., pictogram, ideogrammic compound, phono-semantic compound). "
                        "Strictly forbid any Chinese characters in this field. If the type evolved, provide a short English-only progression with arrows, e.g.: "
                        "pictogram → phono‑semantic compound → ideogrammic compound. Use general reasoning only if the HTML is insufficient."
                    ),
                    field_type="line",
                ),
                CardField(
                    name="description",
                    required=True,
                    description=(
                        "VERY concise arrow sequence A → B → C that shows the formation flow. Each Chinese element MUST be rendered exactly as <chinese character> (<pinyin>, \"<english>\")."
                    ),
                    ai_prompt=(
                        "Rely primarily on the provided Wiktionary HTML. Output a SINGLE LINE arrow sequence (A → B → C…) that shows the formation flow.\n"
                        "STRICT FORMAT RULES:\n"
                        "- Use terse tokens like: pictogram of <chinese character> (<pinyin>, \"<english>\"), semantic: <chinese character> (<pinyin>, \"<english>\"), phonetic: <chinese character> (<pinyin>, \"<english>\"), ideogrammic: <chinese character> (<pinyin>, \"<english>\") + <chinese character> (<pinyin>, \"<english>\").\n"
                        "- EVERY Chinese element MUST be rendered exactly as: <chinese character> (<pinyin>, \"<english>\").\n"
                        "- Keep it minimal, no extra sentences, no trailing period.\n"
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
                        "Rely primarily on the provided Wiktionary HTML. In 1–2 short sentences, explain in plain, intuitive terms how A → B → C flows, why changes happened, and what it meant—no scholarly tone.\n"
                        "If you reference specific components, render Chinese as <chinese character> (<pinyin>, \"<english>\"). Be brief and accessible. Use general reasoning only as a last resort."
                    ),
                    field_type="line",
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
                        "this simplified form was adopted (e.g., component replacement, stroke reduction, graphic regularization)."
                    ),
                    field_type="line",
                    skip_if=lambda ctx: (ctx.get("traditional") or "") == (ctx.get("simplified") or ""),
                ),
            ],
        ),
    ],
)


__all__ = [
    "FRONT_BACK_DIVIDER",
    "CARD_DIVIDER",
    "CardField",
    "CardSchema",
    "FRONT_SCHEMA",
    "BACK_SCHEMA",
]


