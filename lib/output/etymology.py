"""Etymology extraction and processing."""

import re
import time
from typing import Dict, List, Optional, Tuple

from lib.schema.written import BACK_SCHEMA

from lib.common.utils import is_cjk_char, _clean_value
from lib.common.openai import OpenAIClient
from lib.output.html import wiktionary_url_for_word
from lib.output.schema_utils import (
    _field_name_to_key,
    _build_back_json_shape,
    _collect_guidelines,
    _required_optional_keys,
)


# Map common radical variants to their primary standalone characters
RADICAL_VARIANT_TO_PRIMARY: Dict[str, str] = {
    "钅": "金",
    "氵": "水",
    "忄": "心",
    "扌": "手",
    "纟": "糸",
    "艹": "艸",
    "饣": "食",
    "讠": "言",
    "阝": "阜",
}


def _map_radical_variant_to_primary(ch: str) -> str:
    """Map radical variant to primary character."""
    return RADICAL_VARIANT_TO_PRIMARY.get(ch, ch)


def _etymology_complete(back: object) -> bool:
    """Check if etymology fields are complete."""
    if not isinstance(back, dict):
        return False
    et = back.get("etymology")
    if not isinstance(et, dict):
        return False
    t = et.get("type")
    d = et.get("description")
    i = et.get("interpretation")
    return isinstance(t, str) and t.strip() and isinstance(d, str) and d.strip() and isinstance(i, str) and i.strip()


def _parse_component_english_map(description: str) -> Dict[str, str]:
    """Parse component English from description."""
    mapping: Dict[str, str] = {}
    if not isinstance(description, str) or not description:
        return mapping
    for m in re.finditer(r"([^\s()]+)\s*\([^)]*,\s*\"([^\"]+)\"\)", description):
        token = m.group(1)
        en = m.group(2).strip()
        simp = next((c for c in token if is_cjk_char(c)), "")
        if simp and simp not in mapping:
            mapping[simp] = en
    return mapping


def _parse_component_forms_map(description: str) -> Dict[str, Tuple[str, str]]:
    """Parse component forms from description."""
    mapping: Dict[str, Tuple[str, str]] = {}
    if not isinstance(description, str) or not description:
        return mapping
    pattern = re.compile(r"([^\s()]+)(?:\(([^)]+)\))?\s*\([^)]*,\s*\"[^\"]+\"\)")
    for m in pattern.finditer(description):
        simp_token = m.group(1) or ""
        trad_token = m.group(2) or ""
        simp = next((c for c in simp_token if is_cjk_char(c)), "")
        trad = next((c for c in trad_token if is_cjk_char(c)), "")
        if simp:
            mapping[simp] = (simp, trad or simp)
    return mapping


def _collect_components_from_back(back_fields: Dict[str, object]) -> List[str]:
    """Collect component characters from back fields."""
    comps: List[str] = []
    if not isinstance(back_fields, dict):
        return comps
    et = back_fields.get("etymology")
    if isinstance(et, dict):
        raw_present = "component_characters" in et
        raw = et.get("component_characters")
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, str):
                    first_cjk = next((c for c in item if is_cjk_char(c)), "")
                    if first_cjk:
                        mapped = _map_radical_variant_to_primary(first_cjk)
                        if mapped not in comps:
                            comps.append(mapped)
        if not comps and not raw_present:
            desc = et.get("description") if isinstance(et.get("description"), str) else ""
            english_map = _parse_component_english_map(str(desc))
            for ch in english_map.keys():
                if len(ch) == 1 and is_cjk_char(ch):
                    mapped = _map_radical_variant_to_primary(ch)
                    if mapped not in comps:
                        comps.append(mapped)
            for ch in str(desc):
                if len(ch) == 1 and is_cjk_char(ch):
                    mapped = _map_radical_variant_to_primary(ch)
                    if mapped not in comps:
                        comps.append(mapped)
    return comps


def extract_back_fields_from_html(
    simplified: str,
    traditional: str,
    english: str,
    html: str,
    model: Optional[str],
    verbose: bool = False,
    parent_word: Optional[str] = None,
    phrase: str = "",
) -> Dict[str, Dict[str, str] | str]:
    """Extract back fields from HTML using OpenAI."""
    client = OpenAIClient(model=model)
    trad_url = wiktionary_url_for_word(traditional or simplified)
    req, opt = _required_optional_keys()
    system = (
        "You generate back-of-card fields for a Chinese vocabulary flashcard. Output STRICT JSON ONLY matching this shape:\n"
        + _build_back_json_shape()
        + "\nRequired fields: "
        + ", ".join(req)
        + "\nOptional fields: "
        + ", ".join(opt)
        + "\nGuidance (from schema ai_prompts only):\n"
        + _collect_guidelines()
        + "\nHARD CONSTRAINTS:\n"
          "- Return ONLY raw JSON (no markdown, no commentary).\n"
          "- Adhere EXACTLY to field-level guidance from the schema.\n"
          "- If a required value cannot be sourced from the provided HTML (except simplification_rule), return an empty string.\n"
          "- Be concise. Do NOT add extra sentences, labels, or keys.\n"
          "- Do NOT invent facts not present in the HTML (except simplification_rule intuition).\n"
          "- Do NOT change field names or structure.\n"
          "- Use the provided Wiktionary HTML as the PRIMARY source; only the simplification rule may use general knowledge.\n"
          "- Do NOT censor or filter profanity/vulgarity - include exact definitions and translations."
    )
    user_parts = [
        "Headword (simplified): " + simplified,
        "Headword (traditional): " + (traditional or simplified),
        "English gloss: " + english,
    ]
    if phrase:
        user_parts.append("Context phrase from source text: " + phrase)
    user_parts.append("Reference URL (traditional form): " + trad_url)
    user_parts.append("\n\nHTML:\n\n" + html)
    user = "\n".join(user_parts)
    if verbose:
        parent_note = f" (component of {parent_word})" if parent_word else ""
        word_display = traditional or simplified
        print(f"[api] Calling OpenAI for '{word_display}'{parent_note} [model={model or 'default'}]")
    _t0 = time.time()
    try:
        data = client.complete_json(system=system, user=user)
    except KeyboardInterrupt:
        raise
    except Exception as e:
        if verbose:
            print(f"[api] OpenAI call failed: {e}")
        data = {}
    _dt_ms = int((time.time() - _t0) * 1000)
    if verbose:
        print(f"[api] OpenAI complete in {_dt_ms} ms")
        try:
            size_kb = len(html.encode('utf-8')) // 1024
        except Exception:
            size_kb = len(html) // 1024
        print(f"[api] HTML bytes (pruned): {size_kb} KB")
    
    # Build expected JSON structure from schema (defaults)
    def _expected_defaults() -> Dict[str, Dict[str, str] | str | list]:
        out: Dict[str, Dict[str, str] | str | list] = {}
        ctx = {"wiktionary_url": trad_url, "traditional": traditional, "simplified": simplified}
        for f in BACK_SCHEMA.fields:
            key = _field_name_to_key(f.name)
            if f.children:
                child_obj: Dict[str, str | list] = {}
                for ch in f.children or []:
                    if ch.ai_prompt is None and ch.default_provider is None:
                        continue
                    ck = _field_name_to_key(ch.name)
                    if ch.default_provider is not None:
                        child_obj[ck] = ch.default_provider(ctx)
                    else:
                        child_obj[ck] = [] if ch.field_type == "sublist" else ""
                if child_obj:
                    out[key] = child_obj
            else:
                if f.ai_prompt is None and f.default_provider is None:
                    continue
                if f.default_provider is not None:
                    out[key] = f.default_provider(ctx)
                else:
                    out[key] = [] if f.field_type == "sublist" else ""
        return out

    result: Dict[str, Dict[str, str] | str | list] = _expected_defaults()
    if verbose:
        print("[api] defaults constructed for back fields")

    # Merge model data into expected structure
    if isinstance(data, dict):
        for f in BACK_SCHEMA.fields:
            k = _field_name_to_key(f.name)
            if f.children:
                src = data.get(k)
                if isinstance(src, dict):
                    dst = result.get(k)
                    if isinstance(dst, dict):
                        for ch in f.children or []:
                            if ch.ai_prompt is None:
                                continue
                            ck = _field_name_to_key(ch.name)
                            if ck in src:
                                val = src.get(ck)
                                if ch.field_type == "sublist" and isinstance(val, list):
                                    cleaned_items: List[str] = []
                                    for it in val:
                                        s = str(_clean_value(str(it))).strip()
                                        if s.startswith("- "):
                                            s = s[2:].strip()
                                        if s:
                                            cleaned_items.append(s)
                                    dst[ck] = cleaned_items
                                elif isinstance(val, str):
                                    dst[ck] = _clean_value(val.strip())
            else:
                if f.ai_prompt is not None and k in data:
                    val = data.get(k)
                    if f.field_type == "sublist" and isinstance(val, list):
                        cleaned_items: List[str] = []
                        for it in val:
                            s = str(_clean_value(str(it))).strip()
                            if s.startswith("- "):
                                s = s[2:].strip()
                            if s:
                                cleaned_items.append(s)
                        result[k] = cleaned_items
                    elif isinstance(val, str):
                        result[k] = _clean_value(val.strip())
    if verbose:
        print("[api] merge complete; returning back fields")
    return result  # type: ignore[return-value]


def extract_contemporary_usage(
    simplified: str,
    traditional: str,
    english: str,
    html: str,
    model: Optional[str] = None,
    verbose: bool = False,
) -> List[str]:
    """Extract only contemporary usage examples from HTML (for oral mode).
    
    Returns a list of usage strings like:
    - 得体(得體) (détǐ, "appropriate")
    - 得到 (dédào, "obtain")
    """
    client = OpenAIClient(model=model)
    system = """You extract contemporary usage examples for a Chinese vocabulary flashcard.
Output a JSON object with one key "contemporary_usage" containing an array of strings.

FORMAT RULES:
- Each item MUST be a multi-character phrase/compound (no single characters)
- Format: simplified_phrase (pinyin, "english")
- If traditional differs from simplified, show FULL PHRASE in both forms: simplified_phrase(traditional_phrase) (pinyin, "english")
  Example: 又红又专(又紅又專) (pinyin, "meaning") - NOT 又红(紅)又专(專)
- Maximum 4 items
- If no suitable items found, return empty array []
- Do NOT censor or filter profanity/vulgarity - include exact translations

Example output:
{"contemporary_usage": ["得体(得體) (détǐ, \\"appropriate\\")", "得到 (dédào, \\"obtain\\")"]}"""

    user = f"""Headword (simplified): {simplified}
Headword (traditional): {traditional or simplified}
English gloss: {english}

HTML:

{html}"""

    if verbose:
        print(f"[api] Extracting contemporary usage for '{simplified}' [model={model or 'default'}]")
    
    try:
        data = client.complete_json(system=system, user=user)
        usage_list = data.get("contemporary_usage", [])
        if isinstance(usage_list, list):
            result: List[str] = []
            for item in usage_list:
                s = str(item).strip()
                if s.startswith("- "):
                    s = s[2:].strip()
                if s:
                    result.append("- " + s)
            return result
    except Exception as e:
        if verbose:
            print(f"[api] Failed to extract contemporary usage: {e}")
    return []

