#!/usr/bin/env python3
"""Build a "historical forms" progression image for a Chinese character and
optionally attach it to its Mochi card.

Scrapes the "Historical forms of the character X" table from English Wiktionary
(oracle bone -> bronze -> seal -> ...), composites the glyphs into one labeled
strip, and saves it to output/chinese/media/<char>-progression.png.

    python scripts/glyph_progression.py 火
    python scripts/glyph_progression.py 火 --card 5v8HdbPn     # also attach to Mochi
    python scripts/glyph_progression.py 火 --deck pEEsBOAT     # find card by headword + attach

Mochi attach uploads the PNG (POST /cards/:id/attachments/<file>) and inserts
`![Historical forms of X](@media/<file>)` into the card content. MOCHI_API_KEY
must be set (or read from ~/.claude.json).
"""
import argparse
import io
import time
import json
import os
import re
import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
MEDIA = ROOT / "output" / "chinese" / "media"
UA = "FlashcardsTool/1.0 (personal Chinese study project)"
FONT = "/System/Library/Fonts/Supplemental/Arial.ttf"
API = "https://app.mochi.cards/api"


def _session():
    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    return s


def media_path(char: str) -> Path:
    return MEDIA / f"glyph{ord(char):x}.png"


def build(char: str) -> Path | None:
    """Build the progression strip PNG for `char` -> output/chinese/media/
    glyph<cp>.png. Returns the path, or None if the Wiktionary page has no
    historical-forms table. Skips the fetch if the PNG already exists."""
    out = media_path(char)
    if out.exists():
        return out
    s = _session()
    url = "https://en.wiktionary.org/wiki/" + requests.utils.quote(char)
    soup = BeautifulSoup(s.get(url, timeout=30).text, "html.parser")
    tbl = next((t for t in soup.find_all("table")
                if "Historical forms of the character" in t.get_text()), None)
    if not tbl:
        return None
    rows = tbl.find_all("tr")
    imgs_row = next(r for r in rows if r.find("img"))
    imgs = imgs_row.find_all("img")
    captions = []
    for r in rows:
        cells = [c.get_text(" ", strip=True) for c in r.find_all(["td", "th"])]
        if r is not imgs_row and any("script" in c.lower() for c in cells):
            captions = cells

    def fetch(img):
        raw = "https:" + img["src"].split("?")[0]
        # Prefer a larger render (120px is widely available), but always fall
        # back to the page's own src (guaranteed valid). Back off on 429s, which
        # Wikimedia returns under rapid load.
        candidates = [re.sub(r"/\d+px-", "/120px-", raw), raw]
        last = None
        for u in dict.fromkeys(candidates):
            delay = 2.0
            for _ in range(5):
                try:
                    r = s.get(u, timeout=30)
                    if r.status_code == 200 and r.headers.get("content-type", "").startswith("image"):
                        return Image.open(io.BytesIO(r.content)).convert("RGBA")
                    if r.status_code == 429:
                        time.sleep(delay); delay = min(delay * 2, 16); continue
                    last = r.status_code; break
                except Exception as e:  # transient network
                    last = e; time.sleep(delay); delay = min(delay * 2, 16)
        raise RuntimeError(f"no working image for {raw} ({last})")

    glyphs = [fetch(im) for im in imgs]
    font = ImageFont.truetype(FONT, 15)
    CW, GH, PAD = 210, 210, 16
    canvas = Image.new("RGBA", (CW * len(glyphs), GH + 50 + PAD), "white")
    d = ImageDraw.Draw(canvas)
    for i, g in enumerate(glyphs):
        g.thumbnail((CW - 2 * PAD, GH - 2 * PAD), Image.LANCZOS)
        canvas.alpha_composite(g, (i * CW + (CW - g.width) // 2, PAD + (GH - 2 * PAD - g.height) // 2 + PAD))
        cap = captions[i] if i < len(captions) else ""
        l1, l2 = "", ""
        for w in cap.split():
            if d.textlength((l1 + " " + w).strip(), font=font) < CW - 10 and not l2:
                l1 = (l1 + " " + w).strip()
            else:
                l2 = (l2 + " " + w).strip()
        for j, ln in enumerate([l1, l2]):
            d.text((i * CW + (CW - d.textlength(ln, font=font)) // 2, GH + j * 18), ln, fill="black", font=font)
        if i:
            d.line([(i * CW, PAD), (i * CW, GH)], fill="#ccc")
    MEDIA.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(out)
    return out


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
    # Mochi attachment file-names must be alphanumeric ([0-9a-zA-Z]{8,16}); a
    # Chinese char / hyphen is rejected, so key it off the codepoint.
    fname = f"glyph{ord(char):x}.png"
    # 1) upload attachment (multipart, field 'file')
    up = s.post(f"{API}/cards/{card_id}/attachments/{fname}", auth=(key, ""),
                files={"file": (fname, png.open("rb"), "image/png")})
    up.raise_for_status()
    # 2) reference it in the card content (once)
    content = s.get(f"{API}/cards/{card_id}", auth=(key, "")).json()["content"]
    if f"@media/{fname}" not in content:
        block = f"\n- **historical forms:**\n\n![Historical forms of {char}](@media/{fname})\n"
        m = "\n---\n## "
        i = content.rfind(m)
        content = content[:i] + block + content[i:] if i != -1 else content + block
        s.post(f"{API}/cards/{card_id}", auth=(key, ""), json={"content": content}).raise_for_status()
    return fname


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("char")
    ap.add_argument("--card", help="Mochi card id to attach to")
    ap.add_argument("--deck", help="Mochi deck id to find the card by headword")
    args = ap.parse_args(argv)

    png = build(args.char)
    if not png:
        print(f"No historical-forms table on Wiktionary for {args.char}")
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
        fname = attach(args.char, png, card_id)
        print(f"attached {fname} to card {card_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
