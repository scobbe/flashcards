"""Vocabulary extraction via OpenAI."""

from typing import Dict, List, Sequence, Tuple

from lib.common.openai import OpenAIClient
from lib.common.utils import is_cjk_char, keep_only_cjk, unique_preserve_order, filter_substrings


def call_openai_for_vocab_and_forms(
    text: str, model: str | None = None
) -> List[Tuple[str, str, str, str, str]]:
    """Extract vocabulary and forms directly from raw text in one OpenAI call.
    
    Returns list of (simplified, traditional, pinyin, english, phrase) tuples.
    """
    client = OpenAIClient(model=model)
    system = (
        "You are a Chinese vocabulary parser. "
        "Given numbered vocabulary entries, extract each word/phrase with its forms. "
        "Return JSON: {\"entries\": [{\"simplified\": S, \"traditional\": T, \"pinyin\": P, \"english\": E, \"phrase\": EXAMPLE}, ...]} "
        "\n\nIMPORTANT PARSING RULES:\n"
        "1. The VOCABULARY WORD is the FIRST Chinese text on each line (closest to the line number).\n"
        "2. EXAMPLES appear LATER on the same line - these are usage phrases, NOT the vocabulary word.\n"
        "3. Lines may be separated by pipes (|) or other delimiters - the vocab word is ALWAYS first.\n"
        "4. Do NOT confuse examples with the vocabulary word. Examples are longer phrases showing usage.\n"
        "5. Extract: simplified form, traditional form (if different), pinyin with tone marks, short English definition, and example phrases.\n"
        "6. If simplified and traditional are the same, repeat it.\n"
        "7. Return entries in the same order as the input, one entry per numbered line.\n"
        "8. Do NOT censor or filter profanity/vulgarity - include exact definitions for all words."
    )
    user = "Parse this vocabulary list and return JSON:\n\n" + text
    data = client.complete_json(system=system, user=user)
    entries = data.get("entries") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        return []
    
    results: List[Tuple[str, str, str, str, str]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        simp = keep_only_cjk(str(entry.get("simplified", "")).strip())
        trad = keep_only_cjk(str(entry.get("traditional", "")).strip())
        if not simp and trad:
            simp = trad
        if not trad and simp:
            trad = simp
        if not simp:
            continue
        pinyin = str(entry.get("pinyin", "")).strip()
        english = str(entry.get("english", "")).strip()
        phrase = str(entry.get("phrase", "")).strip()
        results.append((simp, trad, pinyin, english, phrase))
    
    return results


def call_openai_forms_for_words(
    words: Sequence[str], model: str | None
) -> List[Tuple[str, str, str, str]]:
    """Ask OpenAI to map each word to simplified/traditional plus English definition."""
    client = OpenAIClient(model=model)
    system = (
        "You convert Chinese vocabulary to their Simplified and Traditional forms and provide English definitions with aligned Pinyin. "
        "Return JSON {\"items\": [{\"simplified\": S, \"traditional\": T, \"pinyin\": P|[P1,P2,...], \"english\": E|[E1,E2,...]}, ...]} in the same length and order as input. "
        "Use only Chinese characters for forms. "
        "\n\nIMPORTANT RULES FOR MULTIPLE PRONUNCIATIONS:\n"
        "1. If a word has MULTIPLE PRONUNCIATIONS with different meanings, return pinyin and english as ARRAYS.\n"
        "2. Order pronunciations from MOST COMMON to LEAST COMMON.\n"
        "3. Each pinyin entry aligns with its corresponding english entry.\n"
        "4. Example for 几: {\"pinyin\": [\"jǐ\", \"jī\"], \"english\": [\"how many; how much\", \"almost; small table\"]}\n"
        "   (jǐ is more common, so it comes first)\n"
        "\nFor single pronunciation words, use strings instead of arrays.\n"
        "Pinyin MUST use tone marks (no numbers). If forms are identical, repeat them.\n"
        "Do NOT censor or filter profanity/vulgarity - include exact definitions for all words."
    )
    user = "Words (comma-separated) in order:\n" + ", ".join(words)
    data: Dict[str, object] = client.complete_json(system=system, user=user)
    triples: List[Tuple[str, str, str, str]] = []
    items = data.get("items") if isinstance(data, dict) else None
    if isinstance(items, list):
        for it in items:
            if isinstance(it, dict):
                s = str(it.get("simplified", "")).strip()
                t = str(it.get("traditional", "")).strip()
                # pinyin may be string or array
                raw_p = it.get("pinyin", "")
                if isinstance(raw_p, list):
                    p_list = [str(x).strip() for x in raw_p if isinstance(x, str) and str(x).strip()]
                    # Use ", " (comma) to separate different pronunciations
                    p = ", ".join(p_list)
                else:
                    p = str(raw_p).strip()
                # english may be string or array
                raw_e = it.get("english", "")
                if isinstance(raw_e, list):
                    e_list = [str(x).strip() for x in raw_e if isinstance(x, str) and str(x).strip()]
                    # Use " | " (pipe) to separate meanings for different pronunciations
                    e = " | ".join(e_list)
                else:
                    e = str(raw_e).strip()
                s = "".join(ch for ch in s if is_cjk_char(ch))
                t = "".join(ch for ch in t if is_cjk_char(ch))
                if s or t:
                    if not s and t:
                        s = t
                    if not t and s:
                        t = s
                    triples.append((s, t, p, e))
    # Fallback if sizes mismatch
    if len(triples) != len(words):
        triples = [(w, w, "", "") for w in words]
    return triples


def heuristic_extract_headwords(text: str) -> List[str]:
    """Extract headwords using heuristic parsing (no AI)."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    candidates: List[str] = []
    for ln in lines:
        processed = ln
        idx = 0
        while idx < len(processed) and processed[idx].isdigit():
            idx += 1
        while idx < len(processed) and processed[idx] in {".", "-", ":", " "}:
            idx += 1
        head = []
        while idx < len(processed) and is_cjk_char(processed[idx]):
            head.append(processed[idx])
            idx += 1
        token = "".join(head)
        if token:
            candidates.append(token)
    candidates = unique_preserve_order(candidates)
    candidates = filter_substrings(candidates)
    return candidates


def extract_phrase_for_word(word: str, text: str) -> str:
    """Extract an example phrase containing the word from the raw text."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    
    # First pass: look for complete sentence examples
    for i, line in enumerate(lines):
        if word not in line:
            continue
        
        cjk_chars = [ch for ch in line if is_cjk_char(ch)]
        if len(cjk_chars) >= len(word) + 2:
            cleaned = line
            while cleaned and cleaned[0] in "0123456789.-: ":
                cleaned = cleaned[1:].strip()
            
            last_cjk_idx = max((i for i, ch in enumerate(cleaned) if is_cjk_char(ch)), default=-1)
            if last_cjk_idx > 0:
                phrase = cleaned[:last_cjk_idx + 1 + 20].strip()
                if len(phrase) >= len(word) and len(phrase) <= 120:
                    return phrase
    
    # Second pass: fallback
    for line in lines:
        if word not in line:
            continue
        
        word_idx = line.find(word)
        if word_idx == -1:
            continue
        
        start = max(0, word_idx - 30)
        end = min(len(line), word_idx + len(word) + 30)
        phrase = line[start:end].strip()
        
        while phrase and phrase[0] in "0123456789.-: ":
            phrase = phrase[1:].strip()
        
        if len(phrase) >= len(word) and len(phrase) <= 100:
            return phrase
    
    return ""

