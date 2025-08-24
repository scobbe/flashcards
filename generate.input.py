import argparse
import csv
import io
import os
import sys
from pathlib import Path
from typing import Iterable, List, Sequence, Set, Tuple, Dict

from openai_helper import OpenAIClient


def is_cjk_char(ch: str) -> bool:
    code = ord(ch)
    if 0x3400 <= code <= 0x9FFF:
        return True
    if 0xF900 <= code <= 0xFAFF:
        return True
    if 0x2E80 <= code <= 0x2EFF:
        return True
    if 0x2F00 <= code <= 0x2FDF:
        return True
    if 0x20000 <= code <= 0x2EBEF:
        return True
    if 0x30000 <= code <= 0x3134F:
        return True
    return False


def keep_only_cjk(text: str) -> str:
    return "".join(ch for ch in text if is_cjk_char(ch))


def unique_preserve_order(items: Iterable[str]) -> List[str]:
    seen: Set[str] = set()
    ordered: List[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def filter_substrings(words: Sequence[str]) -> List[str]:
    result: List[str] = []
    for i, w in enumerate(words):
        keep = True
        for j, other in enumerate(words):
            if i == j:
                continue
            if len(other) > len(w) and w and w in other:
                keep = False
                break
        if keep:
            result.append(w)
    return result


def call_openai_for_vocab(text: str, model: str | None = None) -> List[str]:
    client = OpenAIClient(model=model)
    system = (
        "You are a precise Chinese vocabulary extractor. "
        "Given a raw study note text, extract ONLY the top-level headwords (vocabulary entries). "
        "Ignore examples, sentences, subcomponents/decompositions, and parts-of-speech annotations. "
        "Return a JSON object with a single key 'vocab' whose value is an array of strings. "
        "Each string MUST contain ONLY Chinese characters (no spaces, no Latin letters, no punctuation). "
        "Deduplicate entries. If a word is a substring of another longer word present, exclude the substring."
    )
    user = (
        "Extract top-level vocabulary headwords from this text and return JSON of the form "
        "{\"vocab\":[\"...\"]}.\n\n" + text
    )
    data = client.complete_json(system=system, user=user)
    vocab = data.get("vocab") if isinstance(data, dict) else None
    if not isinstance(vocab, list):
        return []
    cleaned: List[str] = []
    for item in vocab:
        if not isinstance(item, str):
            continue
        only_cjk = keep_only_cjk(item)
        if only_cjk:
            cleaned.append(only_cjk)
    cleaned = unique_preserve_order(cleaned)
    cleaned = filter_substrings(cleaned)
    return cleaned


def heuristic_extract_headwords(text: str) -> List[str]:
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


def format_with_subwords_csv(
    triples: Sequence[Tuple[str, str, str, str]],
    sub_map: Dict[str, Tuple[str, str, str, str]],
    parent_multi: Dict[str, List[str]],
) -> str:
    # CSV columns: simplified, traditional, pinyin, english, relation
    # relation for subwords: sub-word of "<parent english>"; empty for main rows
    buf = io.StringIO()
    writer = csv.writer(buf)
    for simp, trad, pinyin, english in triples:
        writer.writerow([simp, trad, pinyin, english, ""])
        word = simp or trad
        if len(word) > 1:
            seen_tokens: Set[str] = set()
            for ch in word:
                if not is_cjk_char(ch) or ch in seen_tokens:
                    continue
                seen_tokens.add(ch)
                s_simp, s_trad, s_pin, s_eng = sub_map.get(ch, (ch, ch, "", ""))
                writer.writerow([s_simp, s_trad, s_pin, s_eng, f'sub-word of "{english}"'])
            for sub in parent_multi.get(word, []):
                if not sub or sub in seen_tokens:
                    continue
                seen_tokens.add(sub)
                s_simp, s_trad, s_pin, s_eng = sub_map.get(sub, (sub, sub, "", ""))
                writer.writerow([s_simp, s_trad, s_pin, s_eng, f'sub-word of "{english}"'])
    return buf.getvalue()


def find_raw_input_files(root: Path) -> List[Path]:
    # Single supported input format: -input.raw.txt
    return [
        Path(p) for p in sorted(root.rglob("-input.raw.txt")) if Path(p).is_file()
    ]


def call_openai_forms_for_words(words: Sequence[str], model: str | None) -> List[Tuple[str, str, str, str]]:
    # Ask OpenAI to map each word to simplified/traditional plus a short English definition.
    client = OpenAIClient(model=model)
    system = (
        "You convert Chinese vocabulary to their Simplified and Traditional forms and provide up to TWO short English senses with aligned Pinyin. "
        "Return JSON {\"items\": [{\"simplified\": S, \"traditional\": T, \"pinyin\": P|[P1,P2], \"english\": E|[E1,E2]}, ...]} in the same length and order as input. "
        "Use only Chinese characters for forms. For English, include at most TWO senses (2–8 words each), ordered by commonness; if only one sense is clear, return one. "
        "IMPORTANT: Within a single sense, separate near-synonyms with ' or ' (spaces around 'or'). Separate DIFFERENT senses with '; ' (semicolon+space). Return at most two senses. "
        "If two distinct pronunciations map to the two senses, return pinyin as a two-element array aligned by sense; otherwise return a single pinyin string. "
        "Pinyin MUST use tone marks (no numbers). If a form is identical, repeat it."
    )
    user = (
        "Words (comma-separated) in order:\n" + ", ".join(words)
    )
    data: Dict[str, object] = client.complete_json(system=system, user=user)
    triples: List[Tuple[str, str, str, str]] = []
    items = data.get("items") if isinstance(data, dict) else None
    if isinstance(items, list):
        for it in items:
            if isinstance(it, dict):
                s = str(it.get("simplified", "")).strip()
                t = str(it.get("traditional", "")).strip()
                # pinyin may be string or array of up to two
                raw_p = it.get("pinyin", "")
                if isinstance(raw_p, list):
                    p_list = [str(x).strip() for x in raw_p if isinstance(x, str) and str(x).strip()]
                    p = "; ".join(p_list[:2])
                else:
                    p = str(raw_p).strip()
                # english may be string or array of up to two
                raw_e = it.get("english", "")
                if isinstance(raw_e, list):
                    e_list = [str(x).strip() for x in raw_e if isinstance(x, str) and str(x).strip()]
                    e = "; ".join(e_list[:2])
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


def call_openai_subwords_for_words(
    parents: Sequence[str], model: str | None
) -> Dict[str, List[Tuple[str, str, str, str]]]:
    """
    Ask OpenAI to propose meaningful SUBWORDS for each multi-character parent word.

    Returns a mapping: parent -> list of (simplified, traditional, pinyin, english).

    Guidance to the model (enforced in the prompt):
    - Only include subwords that are meaningful lexical items.
    - Prefer contiguous substrings within the parent of length >= 2 (e.g., 人民 in 人民币).
    - You may also include distinct single-character components if they are meaningful on their own.
    - Do not include the parent itself as a subword.
    - Pinyin must use tone marks. Forms must be Chinese characters only.
    - Keep 0–4 subwords per parent; deduplicate and preserve order of first occurrence.
    """
    client = OpenAIClient(model=model)
    # Filter to only multi-character parents to conserve tokens
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
                    # Normalize missing forms
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

def process_file(raw_path: Path, model: str | None, verbose: bool) -> Tuple[Path, List[Tuple[str, str, str, str]]]:
    triples: List[Tuple[str, str, str, str]] = []
    text = raw_path.read_text(encoding="utf-8", errors="ignore")
    if verbose:
        print(f"[info] Extracting vocab via OpenAI: {raw_path}")
    try:
        vocab = call_openai_for_vocab(text, model=model)
    except Exception as e:
        if verbose:
            print(f"[warn] OpenAI extraction failed: {e}; falling back to heuristic parsing")
        vocab = heuristic_extract_headwords(text)

    vocab = [keep_only_cjk(w) for w in vocab if keep_only_cjk(w)]
    vocab = unique_preserve_order(vocab)
    vocab = filter_substrings(vocab)

    # Map to simplified/traditional pairs + english via OpenAI helper
    try:
        triples = call_openai_forms_for_words(vocab, model=model)
    except Exception:
        triples = [(w, w, "", "") for w in vocab]

    # Build subword set to ensure we have english/pinyin for sub-characters
    main_char_map: Dict[str, Tuple[str, str, str, str]] = {}
    for s, t, p, e in triples:
        if len(s or t) == 1:
            main_char_map[s or t] = (s, t, p, e)
    subchars: List[str] = []
    seen_sub: Set[str] = set()
    for s, t, p, e in triples:
        word = s or t
        if len(word) > 1:
            for ch in word:
                if not is_cjk_char(ch) or ch in seen_sub or ch in main_char_map:
                    continue
                seen_sub.add(ch)
                subchars.append(ch)
    sub_map: Dict[str, Tuple[str, str, str, str]] = dict(main_char_map)
    # Discover multi-character sub-words via OpenAI
    parent_multi: Dict[str, List[str]] = {}
    multi_inputs = [s or t for s, t, _, _ in triples if len((s or t)) > 1]
    if multi_inputs:
        try:
            subwords_info = call_openai_subwords_for_words(multi_inputs, model=model)
        except Exception:
            subwords_info = {}
        for parent, subs in subwords_info.items():
            token_list: List[str] = []
            for ss, tt, pp, ee in subs:
                key = ss or tt
                if key and key not in sub_map:
                    sub_map[key] = (ss, tt, pp, ee)
                if key:
                    token_list.append(key)
            if token_list:
                parent_multi[parent] = token_list
    if subchars:
        try:
            sub_triples = call_openai_forms_for_words(subchars, model=model)
        except Exception:
            sub_triples = [(ch, ch, "", "") for ch in subchars]
        for s, t, p, e in sub_triples:
            key = s or t
            if key and key not in sub_map:
                sub_map[key] = (s, t, p, e)

    out_path = raw_path.with_name("-input.parsed.csv")
    # If parsed already exists, skip writing to preserve idempotency
    if out_path.exists():
        if verbose:
            print(f"[skip] Already exists: {out_path}")
        return out_path, triples
    out_path.write_text(format_with_subwords_csv(triples, sub_map, parent_multi), encoding="utf-8")
    if verbose:
        print(f"[ok] Wrote {out_path} ({len(triples)} items + subwords)")
    return out_path, triples


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate -input.parsed.csv from -input.raw.txt")
    parser.add_argument(
        "--root",
        default=str(Path(__file__).parent / "output"),
        help="Root directory to scan (default: ./output)",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("OPENAI_MODEL"),
        help="OpenAI model name (overrides OPENAI_MODEL)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    parser.add_argument("--text", default=None, help=argparse.SUPPRESS)

    args = parser.parse_args(argv)
    root = Path(args.root)
    if not root.exists():
        print(f"[error] Root directory does not exist: {root}", file=sys.stderr)
        return 2

    raw_files = find_raw_input_files(root)
    if args.verbose:
        print(f"[info] Found {len(raw_files)} -input.raw.txt file(s) under {root}")
    if not raw_files:
        return 0

    total_items = 0
    for raw_path in raw_files:
        # Skip if CSV already exists (new format). Ignore legacy parsed .txt files.
        parsed_dash_csv = raw_path.with_name("-input.parsed.csv")
        parsed_csv = raw_path.with_name("input.parsed.csv")
        if parsed_dash_csv.exists() or parsed_csv.exists():
            if args.verbose:
                which = parsed_dash_csv if parsed_dash_csv.exists() else parsed_csv
                print(f"[skip] Parsed file already present: {which}")
            continue
        _, items = process_file(raw_path, model=args.model, verbose=args.verbose)
        total_items += len(items)

    if args.verbose:
        print(f"[done] Total items written: {total_items}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


