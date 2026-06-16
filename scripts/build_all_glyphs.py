#!/usr/bin/env python3
"""Build glyph-progression images for every single character that appears in any
card (headword or component breadcrumb). Resumable: skips chars already built or
already known to have no Wiktionary historical-forms table.

    python scripts/build_all_glyphs.py
"""
import glob
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.glyph_progression import build, media_path, MEDIA  # noqa: E402

NO_TABLE = MEDIA / ".no_table.txt"


def card_chars() -> list[str]:
    chars = set()
    for f in glob.glob("output/chinese/**/output/*.md", recursive=True):
        if os.path.basename(f).startswith("-"):
            continue
        for line in open(f, encoding="utf-8"):
            if not line.startswith("#"):
                continue
            for seg in re.split(r"[→\s]", line):
                seg = re.sub(r"\([^)]*\)", "", seg).strip("#").strip()
                if len(seg) == 1 and ord(seg[0]) > 0x2E7F:
                    chars.add(seg)
    return sorted(chars)


def main():
    MEDIA.mkdir(parents=True, exist_ok=True)
    no_table = set(NO_TABLE.read_text(encoding="utf-8").split()) if NO_TABLE.exists() else set()
    chars = card_chars()
    built = sum(1 for c in chars if media_path(c).exists())
    print(f"{len(chars)} chars; {built} already built, {len(no_table)} known no-table", flush=True)

    new_built = new_none = 0
    for i, ch in enumerate(chars):
        if media_path(ch).exists() or ch in no_table:
            continue
        try:
            out = build(ch)
        except Exception as e:
            print(f"  [err] {ch}: {str(e)[:60]}", flush=True)
            continue
        if out is None:
            no_table.add(ch)
            new_none += 1
            NO_TABLE.write_text(" ".join(sorted(no_table)), encoding="utf-8")
        else:
            new_built += 1
        if (new_built + new_none) % 20 == 0:
            print(f"  ...{i}/{len(chars)}  built+{new_built} notable+{new_none}", flush=True)
        time.sleep(0.6)  # be gentle with Wikimedia
    total = len(glob.glob(str(MEDIA / "glyph*.png")))
    print(f"DONE: built {new_built} new (total {total} images), {len(no_table)} no-table", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
