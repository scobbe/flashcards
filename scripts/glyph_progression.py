#!/usr/bin/env python3
"""CLI to (re)build a character's glyph-progression image and optionally attach
it to its Mochi card. The build logic now lives in lib/output/chinese/glyph.py
and runs inline during normal card generation; this script is for one-offs and
Mochi attachment.

    python scripts/glyph_progression.py 火
    python scripts/glyph_progression.py 火 --card 5v8HdbPn   # also attach to Mochi
    python scripts/glyph_progression.py 火 --deck pEEsBOAT   # find card by headword + attach
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib.output.chinese.glyph import build_progression, media_path, MEDIA, UA  # noqa: E402,F401

API = "https://app.mochi.cards/api"


def _session():
    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    return s


def _key():
    k = os.environ.get("MOCHI_API_KEY")
    if not k:
        try:
            k = json.load(open(Path.home() / ".claude.json"))["mcpServers"]["mochi"]["env"]["MOCHI_API_KEY"]
        except Exception:
            pass
    if not k:
        raise SystemExit("MOCHI_API_KEY not set")
    return k


def _find_card(s, key, deck_id, char):
    bm = None
    while True:
        params = {"deck-id": deck_id, "limit": 100}
        if bm:
            params["bookmark"] = bm
        r = s.get(f"{API}/cards/", auth=(key, ""), params=params).json()
        for c in r.get("docs", []):
            if re.sub(r"\([^)]*\)", "", c.get("name", "")).strip() == char:
                return c
        bm = r.get("bookmark")
        if not r.get("docs") or not bm:
            return None


def attach(char: str, png: Path, card_id: str):
    key = _key()
    s = _session()
    fname = f"glyph{ord(char):x}.png"  # alphanumeric (Mochi rejects 火-/hyphens)
    up = s.post(f"{API}/cards/{card_id}/attachments/{fname}", auth=(key, ""),
                files={"file": (fname, png.open("rb"), "image/png")})
    up.raise_for_status()
    content = s.get(f"{API}/cards/{card_id}", auth=(key, "")).json()["content"]
    if f"@media/{fname}" not in content:
        block = f"\n- **historical forms:**\n\n![Historical forms of {char}](@media/{fname})\n"
        i = content.rfind("\n---\n## ")
        content = content[:i] + block + content[i:] if i != -1 else content + block
        s.post(f"{API}/cards/{card_id}", auth=(key, ""), json={"content": content}).raise_for_status()
    return fname


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("char")
    ap.add_argument("--card", help="Mochi card id to attach to")
    ap.add_argument("--deck", help="Mochi deck id to find the card by headword")
    args = ap.parse_args(argv)

    png = build_progression(args.char)
    if not png:
        print(f"No historical-forms image for {args.char}")
        return 1
    print(f"built {png}")

    card_id = args.card
    if not card_id and args.deck:
        card = _find_card(_session(), _key(), args.deck, args.char)
        if not card:
            print(f"card for {args.char} not found in deck {args.deck}")
            return 1
        card_id = card["id"]
    if card_id:
        print(f"attached {attach(args.char, png, card_id)} to card {card_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
