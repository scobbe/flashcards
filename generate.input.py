import argparse
import csv
import io
import os
import sys
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Sequence, Set, Tuple, Dict
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

from openai_helper import OpenAIClient


# Load .env file on import
_DEF_ENV_LOADED = False


def _load_env_file() -> None:
    global _DEF_ENV_LOADED
    if _DEF_ENV_LOADED:
        return
    _DEF_ENV_LOADED = True
    try:
        here = Path(__file__).parent
        candidates = [here / ".env", here.parent / ".env"]
        for p in candidates:
            if not p.exists():
                continue
            for raw in p.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("export "):
                    line = line[len("export "):].strip()
                if "=" not in line:
                    continue
                k, v = line.split("=", 1)
                key = k.strip()
                val = v.strip().strip('"').strip("'")
                if key and os.environ.get(key) is None:
                    os.environ[key] = val
    except Exception:
        pass


# Call once on import
_load_env_file()

# Thread ID mapping for cleaner log output
_THREAD_IDX_LOCK = threading.Lock()
_THREAD_IDX_MAP: Dict[int, int] = {}
_THREAD_IDX_NEXT = 0

# Store original stdout before wrapping
_ORIGINAL_STDOUT = sys.stdout


class _ThreadPrefixedWriter:
    """Wrapper for stdout that adds thread IDs to output."""
    def __init__(self, wrapped):
        self._wrapped = wrapped
        self._lock = threading.Lock()

    def write(self, s: str) -> int:
        if not isinstance(s, str):
            return 0
        
        # If this is just a newline from print's second write, don't prefix
        if s == "\n":
            with self._lock:
                try:
                    self._wrapped.write("\n")
                    self._wrapped.flush()
                except Exception:
                    pass
            return 1
        
        tid = threading.get_ident()
        # Map OS thread id to small stable index t00..t99
        with _THREAD_IDX_LOCK:
            global _THREAD_IDX_NEXT
            idx = _THREAD_IDX_MAP.get(tid)
            if idx is None:
                idx = _THREAD_IDX_NEXT
                _THREAD_IDX_MAP[tid] = idx
                _THREAD_IDX_NEXT = (_THREAD_IDX_NEXT + 1) % 100
        
        short_tid = f"t{idx:02d}"
        prefix = f"[{short_tid}] "
        
        with self._lock:
            # Split lines and prefix only actual content lines
            parts = s.split("\n")
            has_trailing_newline = len(parts) > 1 and parts[-1] == ""
            
            for i, part in enumerate(parts):
                if part == "" and i == len(parts) - 1:
                    # Skip trailing empty fragment
                    continue
                self._wrapped.write(prefix + part)
                if i < len(parts) - 1:
                    self._wrapped.write("\n")
            
            # If original string had trailing newline, write it now
            if has_trailing_newline:
                self._wrapped.write("\n")
            
            try:
                self._wrapped.flush()
            except Exception:
                pass
        return len(s)

    def flush(self) -> None:
        try:
            self._wrapped.flush()
        except Exception:
            pass

    def __getattr__(self, name):
        return getattr(self._wrapped, name)


# Wrap stdout with thread prefixes
try:
    sys.stdout = _ThreadPrefixedWriter(sys.stdout)
except Exception:
    pass


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


def call_openai_for_vocab_and_forms(text: str, model: str | None = None) -> List[Tuple[str, str, str, str, str]]:
    """Extract vocabulary and forms directly from raw text in one OpenAI call.
    
    Returns list of (simplified, traditional, pinyin, english, phrase) tuples.
    """
    client = OpenAIClient(model=model)
    system = (
        "You are a Chinese vocabulary parser. "
        "Given numbered vocabulary entries, extract each word/phrase with its forms. "
        "Return JSON: {\"entries\": [{\"simplified\": S, \"traditional\": T, \"pinyin\": P, \"english\": E, \"phrase\": EXAMPLE}, ...]} "
        "For each numbered line, extract the FIRST Chinese word/phrase as the vocabulary item. "
        "Provide simplified, traditional (if different), pinyin with tone marks, short English definition, and an example phrase if present. "
        "If simplified and traditional are the same, repeat it. "
        "Return entries in the same order as the input."
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


def extract_phrase_for_word(word: str, text: str) -> str:
    """Extract an example phrase containing the word from the raw text.
    
    Returns a phrase that includes Chinese characters, pinyin, or Latin text
    that contains the word, preferring complete sentence examples.
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    
    # First pass: look for complete sentence examples (lines with the word that look like sentences)
    for i, line in enumerate(lines):
        if word not in line:
            continue
        
        # Check if this line looks like a sentence example (has multiple CJK chars beyond the word)
        cjk_chars = [ch for ch in line if is_cjk_char(ch)]
        if len(cjk_chars) >= len(word) + 2:  # At least 2 more chars than the word
            # Clean up: remove leading numbers, pinyin digits, punctuation
            cleaned = line
            while cleaned and cleaned[0] in "0123456789.-: ":
                cleaned = cleaned[1:].strip()
            
            # Remove trailing pinyin/English if present (anything after the CJK portion)
            # Find the last CJK character and include a bit after it
            last_cjk_idx = max((i for i, ch in enumerate(cleaned) if is_cjk_char(ch)), default=-1)
            if last_cjk_idx > 0:
                # Include up to 20 chars after last CJK to capture pinyin/English
                phrase = cleaned[:last_cjk_idx + 1 + 20].strip()
                
                # If we have a good phrase, return it
                if len(phrase) >= len(word) and len(phrase) <= 120:
                    return phrase
    
    # Second pass: look for any line containing the word (fallback)
    for line in lines:
        if word not in line:
            continue
        
        # Extract context around the word
        word_idx = line.find(word)
        if word_idx == -1:
            continue
        
        start = max(0, word_idx - 30)
        end = min(len(line), word_idx + len(word) + 30)
        phrase = line[start:end].strip()
        
        # Clean up
        while phrase and phrase[0] in "0123456789.-: ":
            phrase = phrase[1:].strip()
        
        if len(phrase) >= len(word) and len(phrase) <= 100:
            return phrase
    
    # If no phrase found, return empty string
    return ""


def _show_progress(stop_event: threading.Event, prefix: str) -> None:
    """Show progress message while waiting (no animation to avoid multi-thread line collision)."""
    # Just print once and wait - animation causes issues with multiple threads
    print(f"{prefix} - Waiting for API response....")
    while not stop_event.is_set():
        time.sleep(0.1)


def format_with_subwords_csv(
    quintuples: Sequence[Tuple[str, str, str, str, str]],
    sub_map: Dict[str, Tuple[str, str, str, str]],
    parent_multi: Dict[str, List[str]],
) -> str:
    # CSV columns: simplified, traditional, pinyin, english, phrase, relation
    # phrase for main rows contains example from text; empty for subwords
    # relation for subwords: sub-word of "<parent english>"; empty for main rows
    buf = io.StringIO()
    writer = csv.writer(buf)
    for simp, trad, pinyin, english, phrase in quintuples:
        writer.writerow([simp, trad, pinyin, english, phrase, ""])
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


def find_raw_input_files(root: Path) -> List[Path]:
    # Single supported input format: -input.raw.txt
    return [
        Path(p) for p in sorted(root.rglob("-input.raw.txt")) if Path(p).is_file()
    ]


def find_raw_grammar_files(root: Path) -> List[Path]:
    # Grammar input format: -input.raw.grammar.txt
    return [
        Path(p) for p in sorted(root.rglob("-input.raw.grammar.txt")) if Path(p).is_file()
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
def call_openai_for_grammar(text: str, model: str | None) -> List[Dict[str, object]]:
    """
    Extract grammar rules from free-form notes.
    Output: list of {description: str, usage_cn: str, examples: [str, ...]}
    """
    client = OpenAIClient(model=model)
    system = (
        "You extract concise Chinese grammar rules from study notes. "
        "Return ONLY JSON: {\"rules\":[{\"description\":string,\"usage_cn\":string,\"examples\":[string,...]}]} . "
        "Examples should be short, max 5 items total across each rule."
    )
    user = "Extract grammar rules from:\n\n" + text
    data = client.complete_json(system=system, user=user)
    rules = data.get("rules") if isinstance(data, dict) else None
    if not isinstance(rules, list):
        return []
    out: List[Dict[str, object]] = []
    for r in rules:
        if not isinstance(r, dict):
            continue
        desc = str(r.get("description", "")).strip()
        usage = str(r.get("usage_cn", "")).strip()
        ex_raw = r.get("examples", [])
        examples: List[str] = []
        if isinstance(ex_raw, list):
            for it in ex_raw:
                s = str(it).strip()
                if s:
                    examples.append(s)
        if desc:
            out.append({"description": desc, "usage_cn": usage, "examples": examples})
    return out


def write_parsed_grammar_csv(raw_path: Path, rules: List[Dict[str, object]], verbose: bool = False) -> Path:
    import csv, json as _json
    out_path = raw_path.with_name("-input.parsed.grammar.csv")
    # Compute relative path from project root
    project_root = Path(__file__).parent.resolve()
    try:
        folder = str(raw_path.parent.relative_to(project_root))
    except ValueError:
        folder = raw_path.parent.name
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        for r in rules:
            desc = str(r.get("description", ""))
            usage = str(r.get("usage_cn", ""))
            ex = r.get("examples", [])
            ex_json = _json.dumps(ex, ensure_ascii=False) if isinstance(ex, list) else "[]"
            w.writerow([desc, usage, ex_json])
    if verbose:
        print(f"[./{folder}] [file] 💾 Created {out_path.name} ({len(rules)} rules)")
    return out_path


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

def process_file(raw_path: Path, model: str | None, verbose: bool, *, force_rebuild: bool = False) -> Tuple[Path, List[Tuple[str, str, str, str, str]]]:
    text = raw_path.read_text(encoding="utf-8", errors="ignore")
    # Compute relative path from project root
    project_root = Path(__file__).parent.resolve()
    try:
        folder = str(raw_path.parent.relative_to(project_root))
    except ValueError:
        folder = raw_path.parent.name
    
    # Single OpenAI call to extract everything
    try:
        if verbose:
            stop_event = threading.Event()
            progress_thread = threading.Thread(
                target=_show_progress,
                args=(stop_event, f"[./{folder}] [api] 🤖 Parsing vocab from {raw_path.name}")
            )
            progress_thread.start()
        
        quintuples = call_openai_for_vocab_and_forms(text, model=model)
        
        if verbose:
            stop_event.set()
            progress_thread.join()
            print(f"[./{folder}] [ok] ✅ Parsed {len(quintuples)} entries")
    except Exception as e:
        if verbose:
            stop_event.set()
            progress_thread.join()
            print(f"[./{folder}] [error] ❌ OpenAI parsing failed: {e}")
        quintuples = []

    # Build subword set to ensure we have english/pinyin for sub-characters
    main_char_map: Dict[str, Tuple[str, str, str, str]] = {}
    for s, t, p, e, _ in quintuples:
        if len(s or t) == 1:
            main_char_map[s or t] = (s, t, p, e)
    subchars: List[str] = []
    seen_sub: Set[str] = set()
    for s, t, p, e, _ in quintuples:
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
    multi_inputs = [s or t for s, t, _, _, _ in quintuples if len((s or t)) > 1]
    if multi_inputs:
        try:
            if verbose:
                stop_event = threading.Event()
                progress_thread = threading.Thread(
                    target=_show_progress,
                    args=(stop_event, f"[./{folder}] [api] 🤖 Getting subwords for {len(multi_inputs)} multi-char words")
                )
                progress_thread.start()
            
            subwords_info = call_openai_subwords_for_words(multi_inputs, model=model)
            
            if verbose:
                stop_event.set()
                progress_thread.join()
                total_subs = sum(len(v) for v in subwords_info.values())
                print(f"[./{folder}] [ok] ✅ Got {total_subs} subwords")
        except Exception:
            if verbose:
                stop_event.set()
                progress_thread.join()
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
            if verbose:
                stop_event = threading.Event()
                progress_thread = threading.Thread(
                    target=_show_progress,
                    args=(stop_event, f"[./{folder}] [api] 🤖 Getting forms for {len(subchars)} component characters")
                )
                progress_thread.start()
            
            sub_triples = call_openai_forms_for_words(subchars, model=model)
            
            if verbose:
                stop_event.set()
                progress_thread.join()
                print(f"[./{folder}] [ok] ✅ Got forms for {len(sub_triples)} components")
        except Exception:
            if verbose:
                stop_event.set()
                progress_thread.join()
            sub_triples = [(ch, ch, "", "") for ch in subchars]
        for s, t, p, e in sub_triples:
            key = s or t
            if key and key not in sub_map:
                sub_map[key] = (s, t, p, e)

    out_path = raw_path.with_name("-input.parsed.csv")
    # If parsed already exists and not forcing, skip writing to preserve idempotency
    if out_path.exists() and not force_rebuild:
        if verbose:
            print(f"[./{folder}] [skip] Already exists: {out_path.name}")
        return out_path, quintuples
    out_path.write_text(
        format_with_subwords_csv(quintuples, sub_map, parent_multi), encoding="utf-8"
    )
    if verbose:
        print(f"[./{folder}] [file] 💾 Created {out_path.name} ({len(quintuples)} items + subwords)")
    return out_path, quintuples


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_cache(cache_path: Path) -> Dict[str, str]:
    if not cache_path.exists():
        return {}
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_cache(cache_path: Path, raw_sha256: str, parsed_filename: str) -> None:
    payload = {
        "raw_sha256": raw_sha256,
        "parsed_file": parsed_filename,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _process_single_raw_file(raw_path: Path, model: str | None, verbose: bool) -> int:
    """Process a single raw input file and return the number of items."""
    # Compute relative path from project root
    project_root = Path(__file__).parent.resolve()
    try:
        folder = str(raw_path.parent.relative_to(project_root))
    except ValueError:
        folder = raw_path.parent.name
    cache_path = raw_path.with_name("-input.cache.json")
    parsed_path = raw_path.with_name("-input.parsed.csv")
    # Compute current raw hash
    current_hash = _sha256_file(raw_path)
    cache = _read_cache(cache_path)
    cached_hash = cache.get("raw_sha256", "")
    # Decide if we need to (re)generate parsed CSV
    need_regen = (current_hash != cached_hash) or (not parsed_path.exists())
    if need_regen:
        if verbose:
            reason = "hash changed" if current_hash != cached_hash else "parsed missing"
            print(f"[./{folder}] [cache-miss] 💥 Regenerating parsed CSV for {raw_path.name} ({reason})")
        _, items = process_file(
            raw_path, model=model, verbose=verbose, force_rebuild=True
        )
        # Update cache
        _write_cache(cache_path, current_hash, parsed_path.name)
        if verbose:
            print(f"[./{folder}] [file] 💾 Updated cache: {cache_path.name}")
        if verbose:
            print(f"[./{folder}] [done] ✅ Processed {len(items)} vocab words from {folder}/")
    else:
        if verbose:
            print(f"[./{folder}] [cache-hit] 🎯 Up-to-date: {raw_path.name}")
        # Count existing items quickly
        try:
            with parsed_path.open("r", encoding="utf-8") as f:
                items = [ln for ln in f.read().splitlines() if ln.strip()]
        except Exception:
            items = []
    return len(items)


def _process_single_grammar_file(gpath: Path, model: str | None, verbose: bool) -> None:
    """Process a single grammar file."""
    # Compute relative path from project root
    project_root = Path(__file__).parent.resolve()
    try:
        folder = str(gpath.parent.relative_to(project_root))
    except ValueError:
        folder = gpath.parent.name
    gcache_path = gpath.with_name("-input.grammar.cache.json")
    parsed_path = gpath.with_name("-input.parsed.grammar.csv")
    current_hash = _sha256_file(gpath)
    cache = _read_cache(gcache_path)
    cached_hash = cache.get("raw_sha256", "")
    need_regen = (current_hash != cached_hash) or (not parsed_path.exists())
    if need_regen:
        if verbose:
            reason = "hash changed" if current_hash != cached_hash else "parsed missing"
            print(f"[./{folder}] [cache-miss] 💥 Regenerating parsed grammar CSV for {gpath.name} ({reason})")
        text = gpath.read_text(encoding="utf-8", errors="ignore")
        if verbose:
            print(f"[./{folder}] [api] 🤖 Extracting grammar rules via OpenAI from {gpath.name}")
        try:
            rules = call_openai_for_grammar(text, model=model)
        except Exception:
            rules = []
        write_parsed_grammar_csv(gpath, rules, verbose=verbose)
        _write_cache(gcache_path, current_hash, parsed_path.name)
        if verbose:
            print(f"[./{folder}] [file] 💾 Updated cache: {gcache_path.name}")
    else:
        if verbose:
            print(f"[./{folder}] [cache-hit] 🎯 Up-to-date grammar: {gpath.name}")


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
        print(f"[main] [error] Root directory does not exist: {root}", file=sys.stderr)
        return 2

    raw_files = find_raw_input_files(root)
    grammar_files = find_raw_grammar_files(root)
    if args.verbose:
        print(f"[main] [info] Found {len(raw_files)} -input.raw.txt file(s) under {root}")
        print(f"[main] [info] Found {len(grammar_files)} -input.raw.grammar.txt file(s) under {root}")
    if not raw_files and not grammar_files:
        return 0

    # Process files in parallel
    total_items = 0
    workers = 5  # Match the number of workers used in generate.output.py
    
    if args.verbose:
        print(f"[main] [info] Parallel workers: {workers}")
    
    # Process vocab files in parallel
    if raw_files:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(_process_single_raw_file, raw_path, args.model, args.verbose): raw_path
                for raw_path in raw_files
            }
            for future in as_completed(futures):
                try:
                    items_count = future.result()
                    total_items += items_count
                except Exception as e:
                    raw_path = futures[future]
                    if args.verbose:
                        print(f"[main] [error] Failed to process {raw_path}: {e}")
                sys.stdout.flush()

    # Process grammar files in parallel
    if grammar_files:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(_process_single_grammar_file, gpath, args.model, args.verbose): gpath
                for gpath in grammar_files
            }
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    gpath = futures[future]
                    if args.verbose:
                        print(f"[main] [error] Failed to process grammar file {gpath}: {e}")

    if args.verbose:
        print(f"\n[main] [done] ✅ Input generation complete! Total items: {total_items}")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


