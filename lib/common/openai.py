import json
import os
from typing import Any, Dict, Optional

from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

try:
    from openai import OpenAI
except Exception:  # pragma: no cover
    OpenAI = None  # type: ignore


# JSON schemas for structured outputs
# Unified "parts" field: components for single chars, character breakdown for multi-char words
CHINESE_SINGLE_CHAR_SCHEMA = {
    "name": "chinese_single_char",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "type": {"type": "string", "description": "Formation type FROM WIKTIONARY: pictogram, ideogram, ideogrammic compound, phono-semantic compound, or semantic compound"},
            "description": {"type": "string", "description": "Brief formation description FROM WIKTIONARY, e.g. 'semantic: X + phonetic: Y'"},
            "interpretation": {"type": "string", "description": "Your own 2-3 sentence plain-language explanation based on the description above"},
            "simplification": {"type": "string", "description": "Why this character was simplified: the intuition/reasoning (e.g. 'simplified radical 饣 reduces strokes while preserving food meaning'), or 'none' if traditional = simplified"},
            "parts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "char": {"type": "string"},
                        "trad": {"type": "string"},
                        "pinyin": {"type": "string"},
                        "english": {"type": "string"}
                    },
                    "required": ["char", "trad", "pinyin", "english"],
                    "additionalProperties": False
                },
                "description": "Component characters (standalone chars only, not radicals like 氵)"
            },
            "examples": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "chinese": {"type": "string", "description": "Simplified with traditional in parens: 我吃饭(我吃飯)。"},
                        "pinyin": {"type": "string", "description": "Pinyin with tone marks"},
                        "english": {"type": "string"}
                    },
                    "required": ["chinese", "pinyin", "english"],
                    "additionalProperties": False
                },
                "description": "2-3 example sentences"
            }
        },
        "required": ["type", "description", "interpretation", "simplification", "parts", "examples"],
        "additionalProperties": False
    }
}

CHINESE_MULTI_CHAR_SCHEMA = {
    "name": "chinese_multi_char",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "type": {"type": "string", "description": "Usually 'compound word'"},
            "description": {"type": "string", "description": "Brief: X + Y = meaning"},
            "interpretation": {"type": "string", "description": "1-2 sentence explanation"},
            "simplification": {"type": "string", "description": "Why this word was simplified: the intuition/reasoning behind the character simplifications, or 'none' if traditional = simplified"},
            "parts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "char": {"type": "string"},
                        "trad": {"type": "string"},
                        "pinyin": {"type": "string", "description": "Pinyin with tone marks"},
                        "english": {"type": "string", "description": "Up to 4 meanings, semicolon-separated"}
                    },
                    "required": ["char", "trad", "pinyin", "english"],
                    "additionalProperties": False
                },
                "description": "Breakdown of each character in the word"
            },
            "examples": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "chinese": {"type": "string", "description": "Simplified with traditional in parens"},
                        "pinyin": {"type": "string", "description": "Pinyin with tone marks"},
                        "english": {"type": "string"}
                    },
                    "required": ["chinese", "pinyin", "english"],
                    "additionalProperties": False
                },
                "description": "2-3 example sentences"
            }
        },
        "required": ["type", "description", "interpretation", "simplification", "parts", "examples"],
        "additionalProperties": False
    }
}

ENGLISH_CARD_SCHEMA = {
    "name": "english_card",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "definition": {
                "type": "array",
                "items": {"type": "string"},
                "description": "1-3 clear, succinct definitions"
            },
            "etymology": {
                "type": "array",
                "items": {"type": "string"},
                "description": "2-3 bullets on linguistic origins (language, root words, derivation)"
            },
            "history": {
                "type": "array",
                "items": {"type": "string"},
                "description": "2-3 bullets on historical background (dates, context, evolution)"
            },
            "pronunciation": {
                "type": "string",
                "description": "Simple syllable breakdown with STRESSED syllable capitalized, e.g. kah-kis-TAH-kruh-see"
            }
        },
        "required": ["definition", "etymology", "history", "pronunciation"],
        "additionalProperties": False
    }
}


class OpenAIClient:
    def __init__(self, model: Optional[str] = None) -> None:
        self.model = model or os.environ.get("OPENAI_MODEL", "gpt-4o")
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not set in environment")
        if OpenAI is None:
            raise RuntimeError("openai package is not available")
        self.client = OpenAI(api_key=api_key, timeout=60.0)

    @retry(reraise=True, stop=stop_after_attempt(4), wait=wait_exponential(multiplier=1, min=1, max=8))
    def complete_structured(self, system: str, user: str, schema: Dict[str, Any]) -> Any:
        """Complete with structured outputs (JSON schema enforcement)."""
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_completion_tokens=4096,
            response_format={"type": "json_schema", "json_schema": schema},
        )
        text = resp.choices[0].message.content or "{}"
        return json.loads(text)

    def _complete_json_once(self, messages: list, verbose: bool = False) -> tuple:
        """Single attempt at JSON completion. Returns (data, is_empty, finish_reason)."""
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_completion_tokens=4096,
            response_format={"type": "json_object"},
        )
        text = resp.choices[0].message.content or "{}"
        finish_reason = resp.choices[0].finish_reason

        try:
            data = json.loads(text)
        except Exception:
            # Some models may wrap arrays in code fences; try to strip
            stripped = text.strip().strip("`")
            data = json.loads(stripped)

        is_empty = (data == {} or not data)
        return data, is_empty, finish_reason

    @retry(reraise=True, stop=stop_after_attempt(4), wait=wait_exponential(multiplier=1, min=1, max=8))
    def complete_json(self, system: str, user: str, schema_hint: Optional[str] = None, verbose: bool = False) -> Any:
        """Complete with basic JSON mode. Retries once on empty response."""
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

        # First attempt
        data, is_empty, finish_reason = self._complete_json_once(messages, verbose)

        # Retry once if empty (transient failure)
        if is_empty:
            print(f"[openai] [warning] Empty response (finish_reason: {finish_reason}), retrying...")
            data, is_empty, finish_reason = self._complete_json_once(messages, verbose)
            if is_empty:
                print(f"[openai] [ERROR] Still empty after retry (finish_reason: {finish_reason})")
            else:
                print(f"[openai] [ok] Retry succeeded")

        return data


