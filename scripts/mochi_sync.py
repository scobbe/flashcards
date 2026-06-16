#!/usr/bin/env python3
"""Sync generated Chinese flashcards into Mochi.

Each `N.<word>.md` card file maps to one Mochi card. Cards are matched to
existing Mochi cards by simplified headword (parenthetical traditional
annotations are stripped, so matching works for both the old `简(繁)` format and
the new per-character format). Matched cards are UPDATED in place via
`POST /cards/:id`, which preserves the card id and its review history. Local
cards with no match are CREATED. Mochi cards with no local match are reported as
orphans (and only trashed with --trash-orphans).

Dry-run by default. Pass --apply to perform writes.

    MOCHI_API_KEY=... python scripts/mochi_sync.py            # dry run
    MOCHI_API_KEY=... python scripts/mochi_sync.py --apply    # write
    MOCHI_API_KEY=... python scripts/mochi_sync.py --apply --only daily/12-27-25
"""
import argparse
import os
import re
import sys
import time
from pathlib import Path

import requests

API = "https://app.mochi.cards/api"
ROOT = Path(__file__).resolve().parent.parent
MEDIA = ROOT / "output" / "chinese" / "media"
_MEDIA_REF = re.compile(r"@media/(\S+?\.png)")


def _upload_media(s, card_id, content):
    """Upload every @media image a card references as a Mochi attachment."""
    if not card_id:
        return
    for fname in dict.fromkeys(_MEDIA_REF.findall(content or "")):
        p = MEDIA / fname
        if not p.exists():
            continue
        with p.open("rb") as fh:
            r = _req(s, "POST", f"{API}/cards/{card_id}/attachments/{fname}",
                     files={"file": (fname, fh, "image/png")})
        if r is not None and r.status_code >= 400:
            print(f"      [warn] attach {fname} -> {r.status_code}")
        time.sleep(0.2)

# repo batch dir (relative to repo root) -> Mochi deck id
DECK_MAP = {
    "output/chinese/class/1-8-26/book": "JHSrVw54",
    "output/chinese/class/12-22-25/book": "r5skEi3f",
    "output/chinese/class/12-22-25/class": "caEyO3Bi",
    "output/chinese/class/8-12-25/book": "aOwZQ6mv",
    "output/chinese/class/8-12-25/class": "2EPkK2Tx",
    "output/chinese/general/common/10000-phrases/chunks/chunk-001": "AtdObAks",
    "output/chinese/general/daily/1-8-26": "3VIUL9uy",
    "output/chinese/general/daily/12-26-25": "fhufsYYG",
    "output/chinese/general/daily/12-27-25": "xhm1819o",
    "output/chinese/class/6-15-26/book": "aSfC8sE5",
    "output/chinese/class/6-15-26/class": "sQY3iY3s",
    "output/chinese/class/6-17-26/book": "oHA8erXe",
    "output/chinese/class/6-8-26/book": "pEEsBOAT",
}

_PARENS = re.compile(r"\([^)]*\)")
# A glyph-progression image block added on the Mochi side (see glyph_progression.py).
# It lives only in Mochi, so preserve it when pushing local content over a card.
_MEDIA_BLOCK = re.compile(r"\n- \*\*historical forms:\*\*\n\n!\[[^\]]*\]\(@media/[^)]+\)\n")


def preserve_media(local: str, mochi: str) -> str:
    """Re-insert any @media historical-forms block from the existing Mochi card
    into the local content (before the reverse-card footer), so syncing doesn't
    strip an image that only exists on the Mochi side."""
    m = _MEDIA_BLOCK.search(mochi or "")
    if not m or m.group(0) in local:
        return local
    block = m.group(0)
    i = local.rfind("\n---\n## ")
    return local[:i] + block + local[i:] if i != -1 else local + block


def headword(text: str) -> str:
    """Simplified headword: strip parenthetical (traditional) annotations."""
    return _PARENS.sub("", text or "").strip()


def session(key: str) -> requests.Session:
    s = requests.Session()
    s.auth = (key, "")
    return s


def _req(s, method, url, **kw):
    """Request with simple 429/5xx backoff (Mochi allows 1 concurrent call)."""
    for attempt in range(6):
        r = s.request(method, url, timeout=60, **kw)
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(1.5 * (attempt + 1))
            continue
        return r
    return r


def fetch_deck_cards(s, deck_id):
    cards, bookmark = [], None
    while True:
        params = {"deck-id": deck_id, "limit": 100}
        if bookmark:
            params["bookmark"] = bookmark
        r = _req(s, "GET", f"{API}/cards/", params=params)
        r.raise_for_status()
        data = r.json()
        # Skip trashed cards - Mochi keeps soft-deleted cards in the deck listing
        # but they are hidden in the app; matching against them would wrongly
        # "update" a deleted card instead of recreating a live one.
        docs = [c for c in data.get("docs", []) if c.get("trashed?") is None]
        cards.extend(docs)
        bookmark = data.get("bookmark")
        if not docs or not bookmark:
            break
        time.sleep(0.15)
    return cards


def local_cards(batch_dir: Path):
    """Return {headword: (path, content)} for N.<word>.md files."""
    out = {}
    for p in sorted(batch_dir.glob("*.md")):
        if p.name.startswith("-output") or p.name.startswith("-"):
            continue
        stem = p.stem  # "12.天气预报"
        word = stem.split(".", 1)[1] if "." in stem else stem
        out[word] = (p, p.read_text(encoding="utf-8"))
    return out


def plan_deck(s, rel, deck_id):
    batch = ROOT / rel / "output"
    local = local_cards(batch)
    mochi = fetch_deck_cards(s, deck_id)

    mochi_by_head = {}
    for c in mochi:
        mochi_by_head.setdefault(headword(c.get("name", "")), []).append(c)

    updates, creates, unchanged, dupes = [], [], [], []
    for word, (path, content) in local.items():
        matches = mochi_by_head.get(word, [])
        if len(matches) > 1:
            dupes.append((word, len(matches)))
            continue
        if not matches:
            creates.append((word, content))
            continue
        card = matches[0]
        effective = preserve_media(content, card.get("content") or "")
        if (card.get("content") or "").strip() != effective.strip():
            updates.append((card["id"], word, effective))
        else:
            unchanged.append(word)

    local_heads = set(local)
    orphans = [c for c in mochi if headword(c.get("name", "")) not in local_heads]
    return dict(rel=rel, deck_id=deck_id, n_local=len(local), n_mochi=len(mochi),
                updates=updates, creates=creates, unchanged=unchanged,
                orphans=orphans, dupes=dupes)


def apply_deck(s, plan, trash_orphans):
    did = plan["deck_id"]
    for cid, word, content in plan["updates"]:
        r = _req(s, "POST", f"{API}/cards/{cid}", json={"content": content})
        r.raise_for_status()
        _upload_media(s, cid, content)
        print(f"    updated {word}")
        time.sleep(0.25)
    for word, content in plan["creates"]:
        r = _req(s, "POST", f"{API}/cards/", json={"content": content, "deck-id": did})
        r.raise_for_status()
        _upload_media(s, r.json().get("id"), content)
        print(f"    created {word}")
        time.sleep(0.25)
    if trash_orphans:
        from datetime import datetime, timezone
        ts = datetime.now(timezone.utc).isoformat()
        for c in plan["orphans"]:
            r = _req(s, "POST", f"{API}/cards/{c['id']}", json={"trashed?": ts})
            r.raise_for_status()
            print(f"    trashed orphan {headword(c.get('name',''))}")
            time.sleep(0.25)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="perform writes (default: dry run)")
    ap.add_argument("--trash-orphans", action="store_true", help="soft-delete Mochi cards with no local match")
    ap.add_argument("--only", help="substring filter on batch path")
    args = ap.parse_args(argv)

    key = os.environ.get("MOCHI_API_KEY")
    if not key:
        print("MOCHI_API_KEY not set", file=sys.stderr)
        return 2
    s = session(key)

    mapping = dict(DECK_MAP)

    tot_u = tot_c = tot_o = 0
    for rel, did in mapping.items():
        if args.only and args.only not in rel:
            continue
        plan = plan_deck(s, rel, did)
        flag = "  ⚠ COUNT MISMATCH" if plan["n_local"] != plan["n_mochi"] else ""
        print(f"\n{rel}  (local={plan['n_local']} mochi={plan['n_mochi']}){flag}")
        print(f"  update={len(plan['updates'])} create={len(plan['creates'])} "
              f"unchanged={len(plan['unchanged'])} orphans={len(plan['orphans'])} dupes={len(plan['dupes'])}")
        if plan["dupes"]:
            print(f"    dupe headwords (skipped): {plan['dupes'][:8]}")
        if plan["orphans"]:
            print(f"    orphan examples: {[headword(c.get('name','')) for c in plan['orphans'][:8]]}")
        tot_u += len(plan["updates"]); tot_c += len(plan["creates"]); tot_o += len(plan["orphans"])
        if args.apply:
            apply_deck(s, plan, args.trash_orphans)

    print(f"\n{'APPLIED' if args.apply else 'DRY RUN'} — totals: "
          f"update={tot_u} create={tot_c} orphans={tot_o}"
          f"{' (trashed)' if (args.apply and args.trash_orphans) else ''}")
    if not args.apply:
        print("Re-run with --apply to write. Orphans are left untouched unless --trash-orphans.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
