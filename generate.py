import argparse
import json
import os
import sys
from pathlib import Path
from typing import Iterable, List, Sequence, Set, Tuple

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
        # Find the first contiguous run of CJK characters after any leading numbering
        processed = ln
        # strip leading numbering like "1 ." or "10 ." or "1." or "1 -"
        idx = 0
        while idx < len(processed) and processed[idx].isdigit():
            idx += 1
        while idx < len(processed) and processed[idx] in {".", "-", ":", " "}:
            idx += 1
        # Now collect CJK run
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


def format_numbered(words: Sequence[str]) -> str:
    lines = [f"{i}. {w}" for i, w in enumerate(words, start=1)]
    return "\n".join(lines) + ("\n" if lines else "")


def find_raw_input_files(root: Path) -> List[Path]:
    return [
        Path(p) for p in sorted(root.rglob("raw.input.txt")) if Path(p).is_file()
    ]


def process_file(raw_path: Path, model: str | None, verbose: bool) -> Tuple[Path, List[str]]:
    text = raw_path.read_text(encoding="utf-8", errors="ignore")
    if verbose:
        print(f"[info] Extracting vocab via OpenAI: {raw_path}")
    try:
        vocab = call_openai_for_vocab(text, model=model)
    except Exception as e:
        if verbose:
            print(f"[warn] OpenAI extraction failed: {e}; falling back to heuristic parsing")
        vocab = heuristic_extract_headwords(text)

    # Final cleaning and filtering just in case
    vocab = [keep_only_cjk(w) for w in vocab if keep_only_cjk(w)]
    vocab = unique_preserve_order(vocab)
    vocab = filter_substrings(vocab)

    out_path = raw_path.with_name("parsed.input.txt")
    out_path.write_text(format_numbered(vocab), encoding="utf-8")
    if verbose:
        print(f"[ok] Wrote {out_path} ({len(vocab)} items)")
    return out_path, vocab


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Parse vocab from output/**/raw.input.txt")
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
    # Kept for compatibility with Makefile, though unused for this generator
    parser.add_argument("--text", default=None, help=argparse.SUPPRESS)

    args, unknown = parser.parse_known_args(argv)
    root = Path(args.root)
    if not root.exists():
        print(f"[error] Root directory does not exist: {root}", file=sys.stderr)
        return 2

    raw_files = find_raw_input_files(root)
    if args.verbose:
        print(f"[info] Found {len(raw_files)} raw.input.txt file(s) under {root}")
    if not raw_files:
        return 0

    total_items = 0
    for raw_path in raw_files:
        _, items = process_file(raw_path, model=args.model, verbose=args.verbose)
        total_items += len(items)

    if args.verbose:
        print(f"[done] Total items written: {total_items}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


