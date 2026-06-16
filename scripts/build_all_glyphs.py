#!/usr/bin/env python3
"""Backfill glyph-progression images for every single character that appears in
any card (headword or component breadcrumb). Generation now builds these inline
for newly-generated cards; this script bulk-builds the library for existing
cards. Resumable — lib.output.chinese.glyph caches built + no-table chars.

    python scripts/build_all_glyphs.py
"""
import glob
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib.output.chinese.glyph import build_progression, media_path, MEDIA  # noqa: E402


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
    return chars


def main():
    # Common CJK first (clean tables); rare radicals/extensions deferred.
    chars = sorted(card_chars(), key=lambda c: (0 if 0x4E00 <= ord(c) <= 0x9FFF else 1, ord(c)))
    have = sum(1 for c in chars if media_path(c).exists())
    print(f"{len(chars)} chars; {have} already built", flush=True)

    built = 0
    for i, ch in enumerate(chars):
        if media_path(ch).exists():
            continue
        if build_progression(ch):   # builds + caches; no-table/transient -> None
            built += 1
        if i % 25 == 0:
            print(f"  ...{i}/{len(chars)}  +{built} new", flush=True)
        time.sleep(1.0)
    total = len(glob.glob(str(MEDIA / "glyph*.png")))
    print(f"DONE: {built} new (total {total} images)", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
