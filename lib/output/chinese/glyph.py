"""Glyph-progression ("historical forms") image building, used inline by card
generation and by scripts/glyph_progression.py.

Scrapes the "Historical forms of the character X" table from English Wiktionary,
composites the glyphs into one labeled strip, and caches it at
output/chinese/media/glyph<codepoint>.png. Best-effort: any failure (no table,
network, Wikimedia throttle) returns None so generation never breaks; chars with
genuinely no table are remembered in media/.no_table.txt so they aren't re-fetched.
"""
import io
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont

from lib.common import is_cjk_char

MEDIA = Path(__file__).parent.parent.parent.parent / "output" / "chinese" / "media"
NO_TABLE = MEDIA / ".no_table.txt"
# Wikimedia requires a policy-compliant UA (contact info) or upload.wikimedia.org
# 429s regardless of rate.
UA = "ChineseFlashcards/1.0 (https://github.com/scobbe/flashcards; scobbe502@gmail.com) python-requests"
FONT = "/System/Library/Fonts/Supplemental/Arial.ttf"

_no_table = None


def media_path(char: str) -> Path:
    return MEDIA / f"glyph{ord(char):x}.png"


def _no_table_set():
    global _no_table
    if _no_table is None:
        _no_table = set(NO_TABLE.read_text(encoding="utf-8").split()) if NO_TABLE.exists() else set()
    return _no_table


def _mark_no_table(char: str):
    s = _no_table_set()
    s.add(char)
    MEDIA.mkdir(parents=True, exist_ok=True)
    NO_TABLE.write_text(" ".join(sorted(s)), encoding="utf-8")


def _fetch_image(s, img):
    raw = "https:" + img["src"].split("?")[0]
    delay = 3.0
    for _ in range(3):
        try:
            r = s.get(raw, timeout=30)
            if r.status_code == 200 and r.headers.get("content-type", "").startswith("image"):
                time.sleep(0.4)
                return Image.open(io.BytesIO(r.content)).convert("RGBA")
            if r.status_code in (429, 503):
                time.sleep(delay); delay = min(delay * 2, 8); continue
            return None
        except Exception:
            time.sleep(delay); delay = min(delay * 2, 8)
    return None


def build_progression(char: str) -> Path | None:
    """Ensure the progression image for `char` exists; return its path or None.

    Cached (skip if built or known no-table). Never raises."""
    if len(char) != 1 or not is_cjk_char(char):
        return None
    out = media_path(char)
    if out.exists():
        return out
    if char in _no_table_set():
        return None
    try:
        s = requests.Session()
        s.headers.update({"User-Agent": UA})
        soup = BeautifulSoup(
            s.get("https://en.wiktionary.org/wiki/" + requests.utils.quote(char), timeout=30).text,
            "html.parser")
        tbl = next((t for t in soup.find_all("table")
                    if "Historical forms of the character" in t.get_text()), None)
        if not tbl:
            _mark_no_table(char)
            return None
        rows = tbl.find_all("tr")
        imgs = next(r for r in rows if r.find("img")).find_all("img")
        captions = []
        for r in rows:
            cells = [c.get_text(" ", strip=True) for c in r.find_all(["td", "th"])]
            if r.find("img") is None and any("script" in c.lower() for c in cells):
                captions = cells
        glyphs = [_fetch_image(s, im) for im in imgs]
        if any(g is None for g in glyphs) or not glyphs:
            return None  # transient image failure - retry on a later generation
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
    except Exception:
        return None  # best-effort: never break generation
