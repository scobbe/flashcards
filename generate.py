import argparse
import os
import re
import sys
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

from openai_helper import OpenAIClient

# Auto-load .env if present
try:
    from dotenv import load_dotenv
    _ENV_PATH = os.path.join(os.path.abspath(os.path.dirname(__file__)), ".env")
    if os.path.exists(_ENV_PATH):
        load_dotenv(_ENV_PATH)
except Exception:
    pass

# Ensure pronunciation normalizer exists before any usage
if 'normalize_pronunciation' not in globals():
    def normalize_pronunciation(raw: str) -> str:
        if not raw:
            return ""
        s = raw
        # Keep only the first segment before 'also' or semicolons
        s = re.split(r"(?i)\balso\b|;", s)[0]
        s = re.sub(r"(?i)mandarin\s*\(.*?\)\s*:\s*", "", s)
        s = re.sub(r"(?i)mandarin:\s*", "", s)
        s = re.sub(r"(?i)pinyin:\s*", "", s)
        s = re.split(r"(?i)\bcantonese:\b", s)[0]
        s = re.sub(r"\([^\)]*\)", "", s)
        s = s.replace("；", ";")
        parts = re.split(r"\s*(?:;|,|/|\.|\bor\b|\band\b|\balso\b)\s*", s, flags=re.IGNORECASE)
        kept: List[str] = []
        token_re = re.compile(r"^[A-Za-zāáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜ ]+$")
        for p in parts:
            pt = p.strip()
            if not pt:
                continue
            if token_re.match(pt) and not re.search(r"\d", pt):
                kept.append(pt)
        if not kept:
            return s.strip()
        # Use only the first pinyin reading to avoid noisy alternates
        return kept[0]


RUNTIME_DIR = os.path.abspath(os.path.dirname(__file__))
WORK_ROOT = os.path.join(RUNTIME_DIR, "output")


def ensure_dir(path: str) -> None:
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)


def now_ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


# Regex validators
REGEX = {
    "front": re.compile(r"^##\s+[A-Za-z0-9 ,;:()'\"./-]+(\s+\(archaic\))?$"),
    "front_sub": re.compile(r"^(###\s+(subword\s+in|component\s+of)\s+\"[A-Za-z0-9 ,;:()'\"./-]+\")?$"),
    "divider": re.compile(r"^---$"),
    "label_character": re.compile(r"^- \*\*Character:\*\* .+$"),
    "label_pron": re.compile(r"^- \*\*Pronunciation:\*\* [a-zA-Zāáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜ/ ]+$"),
    "label_def": re.compile(r"^- \*\*Definition:\*\* .+$"),
    "label_usage": re.compile(r"^- \*\*Contemporary usage:\*\*$"),
    "label_usage_item": re.compile(r"^  - .+ \([a-zA-Zāáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜ' ]+\) - .+$"),
    "label_usage_none": re.compile(r"^None$"),
    "label_etym": re.compile(r"^- \*\*Etymology(\s\([^\)]+\))?:\*\*$"),
    "label_etym_type": re.compile(r"^  - \*\*Type:\*\* .+$"),
    "label_etym_desc": re.compile(r"^  - \*\*Description:\*\* .+$"),
    "label_etym_interp": re.compile(r"^  - \*\*Interpretation:\*\* .+$"),
    "label_etym_ref": re.compile(r"^  - \*\*Reference:\*\* (\[[^\]]+ — Wiktionary\]\(https://en\.wiktionary\.org/wiki/[^/\s\)]+\)|https://[^\s\)]+|None)$"),
    "term": re.compile(r"^(%%%|---|##|###|- \*\*|  - ).*$"),
}


class WiktionaryClient:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "flashcards-cli/1.0 (https://example.local)"
        })

    @staticmethod
    def make_url_for_headword(headword: str) -> str:
        from urllib.parse import quote

        return f"https://en.wiktionary.org/wiki/{quote(headword, safe='')}"

    def fetch_page(self, url: str) -> Tuple[int, str]:
        last_err: Optional[Exception] = None
        for _ in range(3):
            try:
                resp = self.session.get(url, timeout=(10, 40))
                return resp.status_code, resp.text
            except requests.exceptions.RequestException as e:
                last_err = e
        raise last_err  # type: ignore

    def search_then_open(self, headword: str) -> Tuple[Optional[str], Optional[str]]:
        url = self.make_url_for_headword(headword)
        status, html = self.fetch_page(url)
        if status == 200:
            return url, html
        return None, None


def _collect_text_until(next_node, stop_tags: Tuple[str, ...]) -> str:
    parts: List[str] = []
    node = next_node
    while node is not None:
        if getattr(node, 'name', None) in stop_tags:
            break
        parts.append(node.get_text("\n") if hasattr(node, 'get_text') else str(node))
        node = node.next_sibling
    return "\n".join(parts)


def extract_chinese_sections(html: str) -> Dict[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    result = {"chinese_text": "", "etym_text": "", "pron_text": ""}
    # Find the Chinese language section
    chinese_span = soup.find(id="Chinese")
    if chinese_span is None:
        # fallback to full text
        txt = soup.get_text("\n")
        result["chinese_text"] = txt
        result["etym_text"] = ""
        return result
    # h2 parent
    h2 = chinese_span.find_parent(["h2", "h3"]) or chinese_span.parent
    chinese_text = _collect_text_until(h2.next_sibling, ("h2",))
    result["chinese_text"] = chinese_text
    # Inside Chinese section, find Etymology subsection
    ety_span = None
    pron_span = None
    for sp in h2.find_all_next("span", id=True):
        # stop when next language section reached
        par = sp.find_parent(["h2", "h3"]) or sp.parent
        if par and par.name == "h2" and sp.get("id") != "Chinese":
            break
        if sp.get("id", "").startswith("Etymology"):
            ety_span = sp
        if sp.get("id", "") == "Pronunciation":
            pron_span = sp
    if ety_span is not None:
        ety_header = ety_span.find_parent(["h3", "h4"]) or ety_span.parent
        ety_text = _collect_text_until(ety_header.next_sibling, ("h3", "h2"))
        result["etym_text"] = ety_text
    if pron_span is not None:
        pron_header = pron_span.find_parent(["h3", "h4"]) or pron_span.parent
        pron_text = _collect_text_until(pron_header.next_sibling, ("h3", "h2"))
        result["pron_text"] = pron_text
    return result


_CJK_RANGES = (
    "\u3400-\u9FFF"
    "\uF900-\uFAFF"
    "\u2E80-\u2EFF"
    "\u2F00-\u2FDF"
    "\u3000-\u303F"
)


def _is_cjk_char(ch: str) -> bool:
    code = ord(ch)
    return (
        0x3400 <= code <= 0x9FFF or
        0xF900 <= code <= 0xFAFF or
        0x2E80 <= code <= 0x2EFF or
        0x2F00 <= code <= 0x2FDF or
        0x3000 <= code <= 0x303F
    )


def normalize_text_for_cjk(text: str) -> str:
    t = text.replace("\u200b", "").replace("\u200d", "")
    chars: List[str] = []
    prev_cjk = False
    for ch in t:
        if ch.isspace():
            if prev_cjk:
                continue
            else:
                chars.append(" ")
                prev_cjk = False
                continue
        if _is_cjk_char(ch):
            if chars and chars[-1] == " ":
                j = len(chars) - 2
                while j >= 0 and chars[j] == " ":
                    j -= 1
                if j >= 0 and _is_cjk_char(chars[j]):
                    chars.pop()
            chars.append(ch)
            prev_cjk = True
        else:
            chars.append(ch)
            prev_cjk = False
    return "".join(chars)


def fallback_extract_headwords(text: str, max_items: int = 12) -> List[str]:
    pattern = re.compile(r"[\u3400-\u9FFF\uF900-\uFAFF\u2E80-\u2EFF\u2F00-\u2FDF]{2,}")
    found = pattern.findall(text)
    seen = set()
    ordered: List[str] = []
    for tok in found:
        if tok not in seen:
            seen.add(tok)
            ordered.append(tok)
        if len(ordered) >= max_items:
            break
    return ordered


def prompt_openai_parse_headwords(client: OpenAIClient, raw_input_text: str) -> List[str]:
    system = (
        "You are a strict extractor. Given arbitrary Chinese learning text, "
        "return a JSON array of distinct top-level vocabulary headwords to process, "
        "keeping original spacing and script for each headword."
    )
    user = raw_input_text
    data = client.complete_json(system=system, user=user, schema_hint="array of strings")
    if isinstance(data, list):
        return [str(x) for x in data]
    return []


def prompt_openai_single_char_fields(
    client: OpenAIClient,
    headword: str,
    chinese_page_text: str,
    pron_text: str = "",
) -> Dict[str, str]:
    system = (
        "Extract strictly from Wiktionary Chinese content below.\n"
        "Return JSON with keys: english_sense, pronunciation, definition, examples (max 2), etymology_type, etymology_description, etymology_interpretation, script_form (simplified|traditional), other_form (if mapping exists), simplification_explanation (if applicable).\n"
        "Rules:\n"
        "- Pronunciation: Hanyu Pinyin with tone marks; multiple readings separated by ' / '. Extract only the Pinyin from the Pronunciation section; strip IPA/Bopomofo/other languages; prefer the primary reading that matches the most common modern definition.\n"
        "- Definition: pick the most common modern sense for learners (not archaic/rare). Keep it short.\n"
        "- Examples: Format each as 'ZH (pinyin) - EN'.\n"
        "- Etymology Description: preserve the order of details as presented in Wiktionary. Be succinct (one short line).\n"
        "- Etymology Interpretation: explain WHY the Description leads to the current meaning and reading in an intuitive, first‑principles way (e.g., why a pictogram was re‑analyzed into semantic 日 + a new phonetic, and how this shift supports meaning and sound). Err on the side of clarity over brevity. If needed, you may use general knowledge to interpret the WHY, but do not invent facts.\n"
        "- Only use facts present; if absent after full scan, set MISSING."
    )
    user = (
        f"Headword: {headword}\n\n"
        f"Chinese section text:\n\n{chinese_page_text}\n\nPronunciation section (if any):\n\n{pron_text}"
    )
    data = client.complete_json(system=system, user=user)
    if not isinstance(data, dict):
        return {}
    return data


def prompt_openai_multi_word_fields(
    client: OpenAIClient,
    headword: str,
) -> Dict[str, object]:
    system = (
        "For a multi-character Chinese word, generate JSON fields: "
        "pronunciation (Hanyu Pinyin with tone marks), definition (most common learner sense, concise), examples (0-2; 'ZH (pinyin) - EN'), "
        "etymology_type, etymology_description, etymology_interpretation, reference_url (https URL or None). "
        "Etymology Description/Interpretation should be succinct (one short line each). Do not scrape Wiktionary here; general knowledge allowed."
    )
    user = f"Headword: {headword}"
    data = client.complete_json(system=system, user=user)
    if not isinstance(data, dict):
        return {}
    return data


def prompt_openai_pick_english_sense(
    client: OpenAIClient,
    definition_text: str,
) -> str:
    system = (
        "Pick a concise English noun/short phrase (ASCII only) to use as a flashcard front, "
        "based ONLY on the provided Chinese definition text. Return a bare JSON string."
    )
    user = f"Definition text:\n\n{definition_text}"
    data = client.complete_json(system=system, user=user)
    if isinstance(data, str):
        return data.strip()
    return ""


def render_card_front(title: str, subline: Optional[str] = None) -> List[str]:
    lines = [f"## {title}"]
    if subline:
        lines.append(subline)
    return lines


def render_card_body(
    character: str,
    pronunciation: str,
    definition: str,
    examples: List[str],
    etym_type: str,
    etym_desc: str,
    etym_interp: str,
    reference: str,
    simplification_explanation: Optional[str] = None,
    etym_label_suffix: Optional[str] = None,
) -> List[str]:
    lines: List[str] = ["---"]
    lines.append(f"- **Character:** {character}")
    lines.append(f"- **Pronunciation:** {pronunciation}")
    lines.append(f"- **Definition:** {definition}")
    lines.append("- **Contemporary usage:**")
    if examples:
        for e in examples[:2]:
            lines.append(f"  - {e}")
    else:
        lines.append("None")
    etymlabel = "- **Etymology:**" if not etym_label_suffix else f"- **Etymology ({etym_label_suffix}):**"
    lines.append(etymlabel)
    lines.append(f"  - **Type:** {etym_type}")
    lines.append(f"  - **Description:** {etym_desc}")
    lines.append(f"  - **Interpretation:** {etym_interp}")
    lines.append(f"  - **Reference:** {reference}")
    if simplification_explanation:
        lines.append(f"  - **Simplification explanation:** {simplification_explanation}")
    lines.append("%%%")
    return lines


def validate_card_lines(lines: List[str]) -> Tuple[bool, str]:
    if not lines:
        return False, "empty card block"
    idx = 0
    if not REGEX["front"].match(lines[idx]):
        return False, f"invalid front header: '{lines[idx]}'"
    idx += 1
    if idx < len(lines) and lines[idx].startswith("###"):
        if not REGEX["front_sub"].match(lines[idx]):
            return False, f"invalid subline format: '{lines[idx]}'"
        idx += 1
    if idx >= len(lines) or not REGEX["divider"].match(lines[idx]):
        got = lines[idx] if idx < len(lines) else "<EOF>"
        return False, f"missing or invalid divider after front, got '{got}'"
    idx += 1
    if idx >= len(lines) or not REGEX["label_character"].match(lines[idx]):
        got = lines[idx] if idx < len(lines) else "<EOF>"
        return False, f"expected '- **Character:** ...', got '{got}'"
    idx += 1
    if idx >= len(lines) or not REGEX["label_pron"].match(lines[idx]):
        got = lines[idx] if idx < len(lines) else "<EOF>"
        return False, f"expected '- **Pronunciation:** <pinyin>', got '{got}'"
    idx += 1
    if idx >= len(lines) or not REGEX["label_def"].match(lines[idx]):
        got = lines[idx] if idx < len(lines) else "<EOF>"
        return False, f"expected '- **Definition:** ...', got '{got}'"
    idx += 1
    if idx >= len(lines) or not REGEX["label_usage"].match(lines[idx]):
        got = lines[idx] if idx < len(lines) else "<EOF>"
        return False, f"expected '- **Contemporary usage:**', got '{got}'"
    idx += 1
    while idx < len(lines) and (lines[idx].startswith("  - ") or REGEX["label_usage_none"].match(lines[idx])):
        if REGEX["label_usage_none"].match(lines[idx]):
            idx += 1
            break
        if not REGEX["label_usage_item"].match(lines[idx]):
            return False, f"invalid usage example format: '{lines[idx]}'"
        idx += 1
    if idx >= len(lines) or not REGEX["label_etym"].match(lines[idx]):
        got = lines[idx] if idx < len(lines) else "<EOF>"
        return False, f"expected '- **Etymology:**', got '{got}'"
    idx += 1
    if idx >= len(lines) or not REGEX["label_etym_type"].match(lines[idx]):
        got = lines[idx] if idx < len(lines) else "<EOF>"
        return False, f"expected '  - **Type:** ...', got '{got}'"
    idx += 1
    if idx >= len(lines) or not REGEX["label_etym_desc"].match(lines[idx]):
        got = lines[idx] if idx < len(lines) else "<EOF>"
        return False, f"expected '  - **Description:** ...', got '{got}'"
    idx += 1
    if idx >= len(lines) or not REGEX["label_etym_interp"].match(lines[idx]):
        got = lines[idx] if idx < len(lines) else "<EOF>"
        return False, f"expected '  - **Interpretation:** ...', got '{got}'"
    idx += 1
    if idx >= len(lines) or not REGEX["label_etym_ref"].match(lines[idx]):
        got = lines[idx] if idx < len(lines) else "<EOF>"
        return False, f"expected '  - **Reference:** <url>' or 'None', got '{got}'"
    if lines[-1] != "%%%":
        return False, "missing terminating '%%%' line"
    return True, ""


def write_cards_file(headword: str, all_cards_lines: List[List[str]], outdir: Optional[str] = None) -> Tuple[str, int]:
    target_dir = outdir or WORK_ROOT
    if not os.path.isabs(target_dir):
        target_dir = os.path.abspath(os.path.join(RUNTIME_DIR, target_dir))
    ensure_dir(target_dir)
    filename = f"{headword}.md"
    path = os.path.join(target_dir, filename)
    with open(path, "w", encoding="utf-8") as f:
        for block in all_cards_lines:
            for line in block:
                f.write(line + "\n")
    return path, len(all_cards_lines)


def clean_pinyin_text(py: str) -> str:
    # Keep only ASCII letters, tone-marked vowels, spaces, and apostrophes
    allowed = re.compile(r"[A-Za-zāáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜ' ]+")
    pieces = allowed.findall(py or "")
    cleaned = "".join(pieces)
    # Collapse spaces
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def normalize_examples(items: List[object]) -> List[str]:
    out: List[str] = []
    for it in items:
        if isinstance(it, dict):
            zh = str(it.get("zh", "") or it.get("hanzi", "")).strip()
            py_raw = str(it.get("pinyin", "") or it.get("py", "")).strip()
            en = str(it.get("en", "") or it.get("english", "")).strip()
            py = clean_pinyin_text(py_raw)
            if zh and en and py:
                out.append(f"{zh} ({py}) - {en}")
        elif isinstance(it, str):
            s = it.strip()
            # Try to parse and sanitize pinyin inside parentheses
            m = re.match(r"^(?P<zh>.+?)\s*\((?P<py>[^\)]*)\)\s*-\s*(?P<en>.+)$", s)
            if m:
                zh = m.group("zh").strip()
                py = clean_pinyin_text(m.group("py"))
                en = m.group("en").strip()
                if zh and py and en:
                    out.append(f"{zh} ({py}) - {en}")
            elif " - " in s and "(" in s and ")" in s:
                # Fallback accept as-is if it looks close enough
                out.append(s)
    return out


def read_extracted_list(path: str) -> List[str]:
    if not os.path.exists(path):
        return []
    words: List[str] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            m = re.match(r"^\s*(\d+)\s*\.\s*(.+)$", line.strip())
            if m:
                words.append(m.group(2).strip())
            else:
                t = line.strip()
                if t:
                    words.append(t)
    seen = set()
    result: List[str] = []
    for w in words:
        if w not in seen:
            seen.add(w)
            result.append(w)
    return result


def write_extracted_list(path: str, words: List[str]) -> None:
    ensure_dir(os.path.dirname(path))
    with open(path, "w", encoding="utf-8") as f:
        for i, w in enumerate(words, 1):
            f.write(f"{i}. {w}\n")


def extract_headwords_numbered(raw_text: str) -> List[str]:
    lines = raw_text.splitlines()
    words: List[str] = []
    cjk_seq = re.compile(r"[\u3400-\u9FFF\uF900-\uFAFF\u2E80-\u2EFF\u2F00-\u2FDF]{1,}")
    for line in lines:
        s = normalize_text_for_cjk(line)
        if re.match(r"^\s*\d+\s*[\.．]", s):
            rest = re.sub(r"^\s*\d+\s*[\.．]\s*", "", s)
            m = cjk_seq.search(rest)
            if m:
                words.append(m.group(0))
                continue
        m2 = re.match(r"^\s*([\u3400-\u9FFF\uF900-\uFAFF\u2E80-\u2EFF\u2F00-\u2FDF]{1,})\s+(N|V|Adv|Prep|VO|PN|Nu|M)\b", s)
        if m2:
            words.append(m2.group(1))
            continue
    seen = set()
    result: List[str] = []
    for w in words:
        if w not in seen:
            seen.add(w)
            result.append(w)
    return result


def prompt_openai_decompose_components(
    client: OpenAIClient,
    headword: str,
    etym_text: str,
) -> List[Dict[str, str]]:
    system = (
        "You are a strict extractor. Use ONLY the Chinese Etymology subsection text below.\n"
        "If and only if the Etymology explicitly lists named components (e.g., phono-semantic composition), "
        "return a JSON array of { component_headword, english_sense? }. Otherwise return an empty array.\n"
        "Do not infer from glyph shape; do not guess."
    )
    user = (
        f"Headword: {headword}\n\n"
        f"Chinese Etymology text:\n\n{etym_text}"
    )
    data = client.complete_json(system=system, user=user)
    if not isinstance(data, list):
        return []
    return data


def build_component_cards(
    client: OpenAIClient,
    wikiclient: WiktionaryClient,
    parent_english: str,
    headword: str,
    visited: Optional[set] = None,
) -> List[List[str]]:
    if visited is None:
        visited = set()
    if headword in visited:
        return []
    visited.add(headword)

    url, html = wikiclient.search_then_open(headword)
    if not url or not html:
        return []
    sections = extract_chinese_sections(html)
    chinese_text = sections.get("chinese_text") or sections.get("full_text") or ""
    components = prompt_openai_decompose_components(client, headword, sections.get("etym_text", ""))
    results: List[List[str]] = []
    for comp in components:
        comp_hw = str(comp.get("component_headword", "")).strip()
        if not comp_hw:
            continue
        # Fetch component fields
        u2, h2 = wikiclient.search_then_open(comp_hw)
        if not u2 or not h2:
            continue
        sec2 = extract_chinese_sections(h2)
        fields = prompt_openai_single_char_fields(client, comp_hw, sec2.get("chinese_text") or sec2.get("full_text") or "") or {}
        examples = normalize_examples(fields.get("examples", []))[:2]
        english_sense = str(comp.get("english_sense") or fields.get("english_sense") or "").strip()
        if not english_sense:
            english_sense = prompt_openai_pick_english_sense(client, str(fields.get("definition", "")))
        front = render_card_front(
            title=english_sense,
            subline=f"### component of \"{parent_english}\"",
        )
        body = render_card_body(
            character=f"{comp_hw}",
            pronunciation=normalize_pronunciation(str(fields.get("pronunciation", ""))),
            definition=str(fields.get("definition", "")),
            examples=examples,
            etym_type=str(fields.get("etymology_type", "")),
            etym_desc=str(fields.get("etymology_description", "")),
            etym_interp=str(fields.get("etymology_interpretation", "")),
            reference=f"[{comp_hw} — Wiktionary]({wikiclient.make_url_for_headword(comp_hw)})",
        )
        block = front + body
        ok, reason = validate_card_lines(block)
        if ok:
            results.append(block)
            # Recurse deeper
            results.extend(build_component_cards(client, wikiclient, english_sense, comp_hw, visited))
    return results


def process_headword(client: OpenAIClient, wikiclient: WiktionaryClient, headword: str, outdir: Optional[str] = None, verbose: bool = False) -> Tuple[Optional[str], Optional[str]]:
    cards: List[List[str]] = []
    is_multi = len(headword) >= 2

    url, html = wikiclient.search_then_open(headword)
    parent_english = ""
    if url and html:
        sections = extract_chinese_sections(html)
        chinese_text = sections.get("chinese_text") or sections.get("full_text") or ""
        fields = prompt_openai_single_char_fields(client, headword, chinese_text, sections.get("pron_text", "")) or {}
        # Simplified/traditional handling for parent
        etym_label_suffix: Optional[str] = None
        char_label_text = headword
        script_form = str(fields.get("script_form", "")).lower()
        other_form = str(fields.get("other_form", "")).strip()
        if script_form.startswith("simplified") and other_form:
            # Fetch traditional page and override critical fields from it
            u_tr, h_tr = wikiclient.search_then_open(other_form)
            if u_tr and h_tr:
                sec_tr = extract_chinese_sections(h_tr)
                tr_text = sec_tr.get("chinese_text") or sec_tr.get("full_text") or ""
                fields_tr = prompt_openai_single_char_fields(client, other_form, tr_text, sec_tr.get("pron_text", "")) or {}
                if fields_tr:
                    for k in ("pronunciation","definition","etymology_type","etymology_description","etymology_interpretation"):
                        if fields_tr.get(k):
                            fields[k] = fields_tr.get(k)
                    # Prefer traditional reference URL for single-character context
                    url = u_tr
            etym_label_suffix = other_form
            # Avoid redundant parenthetical (X (X))
            char_label_text = f"{headword} ({other_form})" if other_form != headword else headword
        examples = normalize_examples(fields.get("examples", []))[:2]
        parent_english = (str(fields.get("english_sense", "")) or
                          prompt_openai_pick_english_sense(client, str(fields.get("definition", ""))) or
                          headword)
        front = render_card_front(title=parent_english)
        body = render_card_body(
            character=char_label_text,
            pronunciation=normalize_pronunciation(str(fields.get("pronunciation", ""))),
            definition=str(fields.get("definition", "")),
            examples=examples,
            etym_type=str(fields.get("etymology_type", "unspecified")),
            etym_desc=str(fields.get("etymology_description", "unspecified")),
            etym_interp=str(fields.get("etymology_interpretation", "unspecified")),
            reference=f"[{headword} — Wiktionary]({url})",
            etym_label_suffix=etym_label_suffix,
        )
        block = front + body
        ok, reason = validate_card_lines(block)
        if not ok:
            return None, f"BLOCKED: invalid card shape for '{headword}': {reason}"
        cards.append(block)
    else:
        if is_multi:
            multi = prompt_openai_multi_word_fields(client, headword)
            examples = normalize_examples(multi.get("examples", []))[:2]
            parent_english = str(multi.get("english", "")).strip() or str(multi.get("definition", "")).strip() or headword
            front = render_card_front(title=parent_english)
            body = render_card_body(
                character=headword,
                pronunciation=normalize_pronunciation(str(multi.get("pronunciation", ""))),
                definition=str(multi.get("definition", "")),
                examples=examples,
                etym_type=str(multi.get("etymology_type", "unspecified")),
                etym_desc=str(multi.get("etymology_description", "unspecified")),
                etym_interp=str(multi.get("etymology_interpretation", "unspecified")),
                reference=str(multi.get("reference_url") or "None"),
            )
            block = front + body
            ok, reason = validate_card_lines(block)
            if not ok:
                return None, f"BLOCKED: invalid card shape for '{headword}': {reason}"
            cards.append(block)
        else:
            return None, f"BLOCKED: missing Wiktionary entry for '{headword}' — could not retrieve via web"

    # If multi-character, add subword character cards and component recursion
    if is_multi:
        for ch in list(headword):
            u_ch, h_ch = wikiclient.search_then_open(ch)
            if not u_ch or not h_ch:
                return None, f"BLOCKED: missing Wiktionary entry for '{ch}' — could not retrieve via web"
            sec_ch = extract_chinese_sections(h_ch)
            f_ch = prompt_openai_single_char_fields(client, ch, sec_ch.get("chinese_text") or sec_ch.get("full_text") or "", sec_ch.get("pron_text", "")) or {}
            examples_ch = normalize_examples(f_ch.get("examples", []))[:2]
            english_ch = str(f_ch.get("english_sense", "")).strip() or prompt_openai_pick_english_sense(client, str(f_ch.get("definition", "")))
            # Simplified/traditional handling for subword character
            etym_suffix_ch: Optional[str] = None
            char_label_ch = ch
            script_ch = str(f_ch.get("script_form", "")).lower()
            other_ch = str(f_ch.get("other_form", "")).strip()
            if script_ch.startswith("simplified") and other_ch:
                u_ct, h_ct = wikiclient.search_then_open(other_ch)
                if u_ct and h_ct:
                    sec_ct = extract_chinese_sections(h_ct)
                    text_ct = sec_ct.get("chinese_text") or sec_ct.get("full_text") or ""
                    f_ct = prompt_openai_single_char_fields(client, other_ch, text_ct, sec_ct.get("pron_text", "")) or {}
                    if f_ct:
                        for k in ("pronunciation","definition","etymology_type","etymology_description","etymology_interpretation"):
                            if f_ct.get(k):
                                f_ch[k] = f_ct.get(k)
                        u_ch = u_ct
                etym_suffix_ch = other_ch
                # Avoid redundant parenthetical (X (X))
                char_label_ch = f"{ch} ({other_ch})" if other_ch != ch else ch
            front_ch = render_card_front(
                title=english_ch,
                subline=f"### subword in \"{parent_english}\"",
            )
            body_ch = render_card_body(
                character=char_label_ch,
                pronunciation=normalize_pronunciation(str(f_ch.get("pronunciation", ""))),
                definition=str(f_ch.get("definition", "")),
                examples=examples_ch,
                etym_type=str(f_ch.get("etymology_type", "")),
                etym_desc=str(f_ch.get("etymology_description", "")),
                etym_interp=str(f_ch.get("etymology_interpretation", "")),
                reference=f"[{ch} — Wiktionary]({u_ch})",
                etym_label_suffix=etym_suffix_ch,
            )
            block_ch = front_ch + body_ch
            ok, reason = validate_card_lines(block_ch)
            if not ok:
                return None, f"BLOCKED: invalid subword card shape for '{ch}': {reason}"
            cards.append(block_ch)

            # Component recursion
            comp_cards = build_component_cards(client, wikiclient, english_ch, ch)
            for b in comp_cards:
                okc, reasonc = validate_card_lines(b)
                if not okc:
                    return None, f"BLOCKED: invalid component card for '{ch}': {reasonc}"
            cards.extend(comp_cards)

    path, n_cards = write_cards_file(headword, cards, outdir=outdir)
    return f"Wrote {os.path.basename(path)} with {n_cards} card(s) for {headword}.", None


def find_instances(root: str) -> List[str]:
    instances: List[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        if "input.txt" in filenames:
            instances.append(dirpath)
    return sorted(instances)


def interactive_loop(args: argparse.Namespace) -> int:
    ensure_dir(WORK_ROOT)
    wikiclient = WiktionaryClient()
    client: Optional[OpenAIClient] = None

    if args.rules_only:
        print("Rules loaded. Awaiting input.")
        return 0

    if client is None:
        client = OpenAIClient()

    instance_dirs = find_instances(WORK_ROOT)
    if not instance_dirs:
        print("No instances found under ./output (create an input.txt in a subdirectory).")
        return 0

    for inst in instance_dirs:
        print(f"[instance] {inst}")
        input_path = os.path.join(inst, "input.txt")
        extracted_path = os.path.join(inst, "extracted.txt")
        with open(input_path, "r", encoding="utf-8") as f:
            raw_text = f.read()
        if os.path.exists(extracted_path):
            headwords = read_extracted_list(extracted_path)
            print(f"[info] Using existing extracted list: {extracted_path} ({len(headwords)} items)")
        else:
            print("[step] Extracting headwords from numbered entries and POS tags…")
            headwords = extract_headwords_numbered(raw_text)
            if not headwords:
                headwords = fallback_extract_headwords(normalize_text_for_cjk(raw_text))
            if not headwords:
                print("No headwords found for this instance.")
                continue
            write_extracted_list(extracted_path, headwords)
            print(f"[ok] Wrote extracted list to {extracted_path}")
        print(f"[plan] Will process {len(headwords)} headwords → {inst}")
        # Process headwords, skipping existing files
        for idx, hw in enumerate(headwords, 1):
            out_path = os.path.join(inst, f"{hw}.md")
            if os.path.exists(out_path):
                print(f"[skip] {idx}/{len(headwords)} {hw} — already exists at {os.path.basename(out_path)}")
                continue
            print(f"[proc] {idx}/{len(headwords)} {hw} — start")
            msg, err = process_headword(client, wikiclient, hw, outdir=inst, verbose=args.verbose)
            if err:
                print(f"[error] {hw} — {err}")
                print("[halt] Stopping due to BLOCKED. Fix input or schema and re-run; existing files will be skipped.")
                return 1
            print(f"[ok] {hw} — {msg}")
    print("[done] All instances processed.")
    return 0


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Chinese flashcards generator CLI")
    p.add_argument("--rules-only", action="store_true", help="Emit rules loaded line and exit")
    p.add_argument("--verbose", action="store_true", help="Print progress for streaming-like feedback")
    return p


def main() -> int:
    parser = build_argparser()
    args = parser.parse_args()
    try:
        return interactive_loop(args)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())


