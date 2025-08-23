import argparse
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup  # type: ignore


def read_parsed_input(parsed_path: Path) -> List[Tuple[str, str, str, str]]:
    rows: List[Tuple[str, str, str, str]] = []
    if parsed_path.suffix.lower() == ".csv":
        import csv
        with parsed_path.open("r", encoding="utf-8") as f:
            reader = csv.reader(f)
            for rec in reader:
                if not rec:
                    continue
                simp = rec[0].strip() if len(rec) > 0 else ""
                trad = rec[1].strip() if len(rec) > 1 else simp
                eng = rec[2].strip() if len(rec) > 2 else ""
                rel = rec[3].strip() if len(rec) > 3 else ""
                if simp:
                    rows.append((simp, trad, eng, rel))
    else:
        for line in parsed_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            if "." in line:
                _, rest = line.split(".", 1)
            else:
                rest = line
            pieces = [p.strip() for p in rest.split(",")]
            simp = pieces[0] if len(pieces) > 0 else rest.strip()
            trad = pieces[1] if len(pieces) > 1 else simp
            eng = pieces[2] if len(pieces) > 2 else ""
            rel = pieces[3] if len(pieces) > 3 else ""
            if simp:
                rows.append((simp, trad, eng, rel))
    return rows


def wiktionary_url_for_word(word: str) -> str:
    # Use English Wiktionary which contains Chinese entries
    return f"https://en.wiktionary.org/wiki/{requests.utils.requote_uri(word)}"


def fetch_wiktionary_html_status(word: str, timeout: float = 20.0) -> Tuple[str, int]:
    url = wiktionary_url_for_word(word)
    try:
        resp = requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": "flashcards-script/1.0 (+https://example.local)"},
        )
        status = resp.status_code
        text = resp.text if resp.text is not None else ""
        return text, status
    except Exception:
        # Treat network errors as 0 status with empty body
        return "", 0


def sanitize_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    # Remove scripts and styles
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return str(soup)


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


def section_header(word: str) -> str:
    return f"<!-- word: {word} -->\n<h1>{word}</h1>\n"


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def build_row_map(rows: List[Tuple[str, str, str, str]]) -> Dict[str, Dict[str, str]]:
    mapping: Dict[str, Dict[str, str]] = {}
    for simp, trad, eng, _ in rows:
        card = {"english": eng, "traditional": trad or simp, "simplified": simp or trad}
        if simp and simp not in mapping:
            mapping[simp] = card
        if trad and trad not in mapping:
            mapping[trad] = card
    return mapping


def write_simple_card_md(out_dir: Path, word: str, english: str, traditional: str, simplified: str, relation: str) -> Path:
    md_path = out_dir / f"{word}.md"
    parts: List[str] = []
    parts.append(f"## {english}")
    # If relation indicates subword, add subheader
    rel = relation.strip()
    if rel:
        # Expecting format like: subword of "<parent>"
        parts.append(f"### {rel}")
    parts.append("---")
    parts.append(f"- **Traditional:**: {traditional}")
    parts.append(f"- **Simplified:**: {simplified}")
    parts.append("%%%")
    content = "\n".join(parts) + "\n"
    md_path.write_text(content, encoding="utf-8")
    return md_path


def process_folder(folder: Path, model: Optional[str], verbose: bool, delay_s: float) -> Tuple[int, int]:
    # Prefer new CSV filenames with leading dash, then non-dash; fall back to legacy txt
    parsed_path = folder / "-input.parsed.csv"
    if not parsed_path.exists():
        alt = folder / "input.parsed.csv"
        if alt.exists():
            parsed_path = alt
        else:
            legacy = folder / "parsed.input.txt"
            if legacy.exists():
                parsed_path = legacy
    if not parsed_path.exists():
        if verbose:
            print(f"[skip] No -input.parsed.csv in {folder}")
        return 0, 0
    rows = read_parsed_input(parsed_path)
    if verbose:
        print(f"[info] {folder}: {len(rows)} word(s)")
    out_dir = folder
    successes = 0
    for simp, trad, eng, rel in rows:
        word = simp or trad
        try:
            md_path = out_dir / f"{word}.md"
            if md_path.exists():
                if verbose:
                    print(f"[skip] Card already exists: {md_path.name}")
                continue
            html_path = out_dir / f"{word}.input.html"
            if html_path.exists():
                combined_html = html_path.read_text(encoding="utf-8", errors="ignore")
                if verbose:
                    print(f"[info] Using cached HTML for {word}")
            else:
                # Build combined HTML: simplified/traditional sections (if distinct)
                combined_sections: List[str] = []
                fetched_set: Dict[str, bool] = {}
                # Fetch simplified and traditional forms distinctly (avoid redundant fetches)
                for form in [simp, trad]:
                    form = (form or "").strip()
                    if not form or form in fetched_set:
                        continue
                    fetched_set[form] = True
                    form_html, form_status = fetch_wiktionary_html_status(form)
                    if form_status == 200 and form_html:
                        combined_sections.append(section_header(form) + sanitize_html(form_html))
                    else:
                        combined_sections.append(section_header(form))
                    if delay_s > 0:
                        time.sleep(delay_s)
                combined_html = "\n\n".join(combined_sections)
                # Always write a .input.html, even if empty sections
                html_path.write_text(combined_html, encoding="utf-8")
            # Build single card markdown directly from the row values
            write_simple_card_md(
                out_dir,
                word,
                eng,
                trad or word,
                simp or word,
                rel,
            )
            successes += 1
            if verbose:
                print(f"[ok] Card for {word}")
        except Exception as e:
            if verbose:
                print(f"[error] {word}: {e}")
        if delay_s > 0:
            time.sleep(delay_s)
    return len(rows), successes


def find_parsed_folders(root: Path) -> List[Path]:
    # Prefer new CSV filenames with leading dash, then non-dash; fall back to legacy txt
    folders: List[Path] = []
    seen = set()
    for pattern in ["-input.parsed.csv", "input.parsed.csv", "parsed.input.txt"]:
        for path in root.rglob(pattern):
            parent = Path(path).parent
            if parent not in seen:
                folders.append(parent)
                seen.add(parent)
    folders.sort()
    return folders


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate flashcard .md files from parsed vocab (one-to-one) and fetch combined HTML")
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
        "--delay",
        type=float,
        default=0.0,
        help="Optional delay in seconds between requests to Wiktionary",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    args = parser.parse_args(argv)

    root = Path(args.root)
    if not root.exists():
        print(f"[error] Root directory does not exist: {root}", file=sys.stderr)
        return 2

    folders = find_parsed_folders(root)
    if args.verbose:
        print(f"[info] Found {len(folders)} folder(s) with -input.parsed.csv under {root}")
    total_words = 0
    total_cards = 0
    for folder in folders:
        words, cards = process_folder(folder, args.model, args.verbose, args.delay)
        total_words += words
        total_cards += cards

    if args.verbose:
        print(f"[done] Processed {total_words} word(s), created {total_cards} card(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


