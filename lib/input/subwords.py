"""Subword extraction and CSV formatting."""

import csv
import io
from typing import Dict, List, Sequence, Set, Tuple

from lib.common.openai import OpenAIClient
from lib.common.utils import is_cjk_char, keep_only_cjk


def call_openai_subwords_for_words(
    parents: Sequence[str], model: str | None
) -> Dict[str, List[Tuple[str, str, str, str]]]:
    """Ask OpenAI to propose meaningful SUBWORDS for each multi-character parent word.

    Returns a mapping: parent -> list of (simplified, traditional, pinyin, english).
    """
    client = OpenAIClient(model=model)
    # Filter to only multi-character parents
    parents = [p for p in parents if isinstance(p, str) and keep_only_cjk(p) and len(p) > 1]
    if not parents:
        return {}

    system = (
        "You decompose each multi-character Chinese headword into a SHORT list of meaningful subwords. "
        "Follow these STRICT rules and return ONLY JSON.\n"
        "Rules:\n"
        "- Consider only the provided parents.\n"
        "- Prefer contiguous substrings of length >= 2 that are common words (e.g., 人民 in 人民币).\n"
        "- You may also include single characters from the parent that are meaningful standalone words.\n"
        "- Do NOT include the parent itself; do NOT include duplicates.\n"
        "- Limit to the most salient 0–4 items per parent.\n"
        "- Use only Chinese characters for forms. Pinyin MUST use diacritical tone marks.\n"
        "- Do NOT censor or filter profanity/vulgarity - include exact definitions for all words.\n"
        "Output shape: {\"items\":[{\"parent\": P, \"subwords\":[{\"simplified\": S, \"traditional\": T, \"pinyin\": Py, \"english\": En}, ...]}]}"
    )
    user = "Parents (comma-separated, in order):\n" + ", ".join(parents)

    data = client.complete_json(system=system, user=user)
    result: Dict[str, List[Tuple[str, str, str, str]]] = {}
    items = data.get("items") if isinstance(data, dict) else None
    if isinstance(items, list):
        for it in items:
            if not isinstance(it, dict):
                continue
            parent = keep_only_cjk(str(it.get("parent", "")))
            if not parent:
                continue
            subs_raw = it.get("subwords")
            sub_list: List[Tuple[str, str, str, str]] = []
            if isinstance(subs_raw, list):
                for sub in subs_raw:
                    if not isinstance(sub, dict):
                        continue
                    s = keep_only_cjk(str(sub.get("simplified", "")).strip())
                    t = keep_only_cjk(str(sub.get("traditional", "")).strip())
                    if not s and t:
                        s = t
                    if not t and s:
                        t = s
                    if not (s or t):
                        continue
                    if s == parent or t == parent:
                        continue
                    pinyin = str(sub.get("pinyin", "")).strip()
                    english = str(sub.get("english", "")).strip()
                    sub_list.append((s or t, t or s, pinyin, english))
            # Deduplicate while preserving order
            seen_keys: Set[str] = set()
            cleaned: List[Tuple[str, str, str, str]] = []
            for s, t, p, e in sub_list:
                key = s or t
                if key and key not in seen_keys:
                    seen_keys.add(key)
                    cleaned.append((s, t, p, e))
            if cleaned:
                result[parent] = cleaned
    return result


def format_with_subwords_csv(
    quintuples: Sequence[Tuple[str, str, str, str, str]],
    sub_map: Dict[str, Tuple[str, str, str, str]],
    parent_multi: Dict[str, List[str]],
    skip_subwords: bool = False,
) -> str:
    """Format vocabulary with subwords as CSV.
    
    CSV columns: simplified, traditional, pinyin, english, phrase, relation
    
    Args:
        quintuples: Main vocabulary entries
        sub_map: Character -> forms mapping
        parent_multi: Parent word -> subword list
        skip_subwords: If True, skip all subword rows (for oral mode)
    """
    buf = io.StringIO()
    writer = csv.writer(buf)
    for simp, trad, pinyin, english, phrase in quintuples:
        writer.writerow([simp, trad, pinyin, english, phrase, ""])
        # Skip subword rows for oral mode
        if skip_subwords:
            continue
        word = simp or trad
        if len(word) > 1:
            seen_tokens: Set[str] = set()
            for ch in word:
                if not is_cjk_char(ch) or ch in seen_tokens:
                    continue
                seen_tokens.add(ch)
                s_simp, s_trad, s_pin, s_eng = sub_map.get(ch, (ch, ch, "", ""))
                writer.writerow([s_simp, s_trad, s_pin, s_eng, "", f'sub-word of "{english}"'])
            for sub in parent_multi.get(word, []):
                if not sub or sub in seen_tokens:
                    continue
                seen_tokens.add(sub)
                s_simp, s_trad, s_pin, s_eng = sub_map.get(sub, (sub, sub, "", ""))
                writer.writerow([s_simp, s_trad, s_pin, s_eng, "", f'sub-word of "{english}"'])
    return buf.getvalue()

