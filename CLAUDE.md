# Agent context — flashcards

Chinese (and English) flashcard generator. Raw vocab → parsed CSV → recursive
`.md` cards → optionally synced into Mochi. Read this before touching generation,
Mochi sync, or the Teams reader — these are the traps that have bitten us.

## Layout
- `output/chinese/<class|general>/<id>/<book|class>/` — a batch. `input/` has
  `-config.json` + `-input.raw.txt`; `input-parsed/-input.parsed.csv` is the
  parsed vocab; `output/` has `N.<word>.md` cards + `-output.md`.
- Class batches: `output/chinese/class/<M-D-YY>/{book,class}/`. Mochi decks
  mirror this tree: a `<date>` deck with `book` / `class` subdecks.
- `scripts/` — `mochi_sync.py`, `teams_personal.py`, `glyph_progression.py`.
- Use `.venv/bin/python`. `OPENAI_API_KEY` in `.env` (auto-loaded).

## Generation — avoid silent card loss
- **`generate.py` re-parses the raw input.** Parsing a long list in one OpenAI
  call can silently truncate (drop entries) → fewer cards → on regen it CLEARS
  the output dir and rebuilds fewer, deleting cards. Guards exist (chunked parse
  at `VOCAB_PARSE_BATCH_SIZE`; `_process_raw_input` raises on a short parse), but:
- **To re-render existing cards with new formatting WITHOUT re-parsing, call
  `process_chinese_folder(<batch>/output)` directly** (reads the existing parsed
  CSV; never re-parses). Re-running is cache-hit/cheap (only archaic components
  with no examples regenerate). This is how to safely apply formatting changes
  across all batches.
- After any bulk regen, verify per-batch card count == parsed-input word count.

## Card formatting — traditional-form parens
- Traditional annotations are minimized per character via
  `collapse_identical_parens(line, empty_slots=True)` in `write_card_md`:
  fully-identical runs collapse (`糸(糸)`→`糸`); in a mixed run every char gets a
  slot — differing chars `字(繁)`, identical chars an empty `字( )`. The empty
  slots are required so Mochi renders each char's ruby centered (without them the
  traditional ruby drifts across the run). Applied to ALL lines incl. examples.

## Mochi sync (`scripts/mochi_sync.py`) — the big traps
- **`DELETE /cards/:id` is a SOFT-trash, not a real delete.** Trashed cards stay
  in `GET /cards?deck-id=...` listings but are HIDDEN in the app. You CANNOT
  un-trash via the API (`trashed?` is a "disallowed key" on update). So:
  - **Always filter `trashed? is None`** when counting/matching/auditing, or you
    will think dead cards are present (this caused a "9 of 30 showing" bug).
  - To "remove" cards prefer leaving them; a dedupe that DELETEs leaves trash
    cruft. To restore lost ones, just re-sync (it recreates live cards).
- **Attachment file-names must be alphanumeric `[0-9a-zA-Z]{8,16}` + ext.**
  Chinese chars / hyphens → 422. Upload via multipart `POST
  /cards/:id/attachments/<file>` (form field `file`), NOT in the card body.
  Reference in content as `![](@media/<file>)`.
- Card update = `POST /cards/:id` with partial fields; it MERGES (content/other
  fields preserved), so moving a card is `POST {"deck-id": X}` and is safe.
- `mochi_sync` matches by simplified headword (strips parens from `name`),
  updates content in place (preserves review history), **ignores trashed cards**,
  and **preserves `@media` historical-forms image blocks** so syncing doesn't
  strip glyph-progression images.
- API: **1 concurrent request**, 429 on bursts — keep sequential with small
  sleeps. Key lives in `~/.claude.json`
  (`mcpServers.mochi.env.MOCHI_API_KEY`); `mochi_sync` reads `MOCHI_API_KEY`:
  `export MOCHI_API_KEY=$(python -c "import json;print(json.load(open('$HOME/.claude.json'))['mcpServers']['mochi']['env']['MOCHI_API_KEY'])")`
- Always `--dry-run` (default) first; only `--apply` after the plan looks right.

## Teams reader (`scripts/teams_personal.py`)
- Personal Teams (Teams For Life, teams.live.com) has **no Graph API**. We read
  the local new-Teams v2 IndexedDB/LevelDB cache (`WV2Profile_tfl`), read-only.
- `messageType` is `Text` / `RichText` / `RichText/Html` / … — accept any
  `RichText*` (only matching `RichText` exactly hid real messages). Content may
  be `bytes`.
- **Opening a chat re-caches its ENTIRE history with every message stamped at the
  same sync minute** (`clientArrivalTime` = sync time). The real day's lesson is
  the run of messages with distinct, spaced timestamps — don't treat the big
  same-timestamp block as "today."
- Only locally-cached chats are available; one contact can have multiple threads.

## Glyph progressions (`scripts/glyph_progression.py`)
- Builds a "historical forms" strip from Wiktionary and attaches it to a Mochi
  card. Wiktionary/Wikimedia rate-limits (429) and only renders some thumb sizes
  — back off and fall back to the page's own src. Attach name = `glyph<cp>.png`.

## Misc
- Don't commit secrets. Commit/push only when asked. Reusable interactive flows
  live as slash commands in `.claude/commands/` (`/generate-flashcards`,
  `/class-vocab-from-teams`).
