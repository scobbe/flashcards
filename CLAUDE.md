# Agent context — flashcards

Chinese (and English) flashcard generator. Raw vocab → parsed CSV → recursive
`.md` cards → optionally synced into Mochi. Read this before touching generation,
Mochi sync, or the Teams reader — these are the traps that have bitten us.

## Layout
- `output/chinese/<class|general>/<id>/<book|class>/` — a batch. `input/` has
  `-config.json` + `-input.raw.txt`; `input-parsed/-input.parsed.csv` is the
  parsed vocab; `output/` has `N.<word>.md` cards + `-output.md`.
- Class batches: `output/chinese/class/<YY-MM-DD>/{book,class}/`. Date ids are
  **`YY-MM-DD`** (year-month-day, zero-padded; `25-12-27` = 27 Dec 2025) — see
  `lib/common/dates.py`. This big-endian form sorts chronologically as text, so
  a plain `ls` is already oldest→newest; `scripts/list_batches.py <dir>` also
  prints each id's date. Mochi decks mirror this tree: a `<date>` deck with
  `book` / `class` subdecks.
- `scripts/` — `mochi_sync.py`, `teams_personal.py`, `glyph_progression.py`,
  `list_batches.py`, `audit_cards.py`.
- Use `.venv/bin/python`. `OPENAI_API_KEY` in `.env` (auto-loaded).

## Card audit (`lib/output/chinese/audit.py`, `scripts/audit_cards.py`)
- A **post-generation audit** runs automatically at the end of `generate.py`
  (deterministic, no API) and prints a flag report. It scans the rendered cards
  for: role-word/empty definitions, Old-Chinese `(OC *…)` leaks, empty/vacuous
  interpretations (high-precision regex), role-word **component glosses** (these
  aren't cleaned at render, unlike subcard definitions), missing pinyin, and
  per-batch card-count vs parsed-input mismatch. Errors gate (CLI exits 1).
- **Vacuous interpretations can't be caught by regex reliably** — run
  `scripts/audit_cards.py --llm [dir]` for an LLM judge. It is a *review list*
  (some false positives expected); it is calibrated so honest phono-semantic
  notes ("semantic radical + a part for sound") and pictograms are GOOD, NOT
  vacuous — never "fix" those by forcing a mechanism (that invites fabrication).

## LLM provider (`get_llm_client`) — OpenAI or Claude
- All generation goes through `get_llm_client(model)` (lib/common). Default is
  OpenAI (`OPENAI_API_KEY`). Set `FLASHCARD_LLM=claude` to use Claude instead.
- **Claude auth = subscription OAuth, not an API key.** `ClaudeClient` keeps a
  POOL of OAuth tokens (`sk-ant-oat-…` from `claude setup-token`) and rotates to
  the next on a failure a different token could fix — `auth` / `rate_limit` /
  `quota` (mirrors the sonoma scan-framework); a limited token is parked on a
  cooldown. Tokens from `CLAUDE_OAUTH_TOKENS` (comma/space list),
  `CLAUDE_OAUTH_TOKEN_1/2/3`, or `~/.config/flashcards/claude_oauth_tokens`; with
  none set it uses the logged-in `claude` CLI session (no rotation).
- Transport: `anthropic` SDK if `ANTHROPIC_API_KEY` is set, else the `claude`
  CLI (subscription — flat-rate, so the per-call `total_cost_usd` it prints is the
  API-equivalent, NOT money spent; the real constraint is the plan's usage window).
  `_call_cli` strips the agent harness — `--system-prompt` (ours), `--tools ""`,
  `--strict-mcp-config`, `--setting-sources ""` — cutting per-call overhead from
  ~23k tokens to ~140 and ~halving latency (no quality change). `--bare` is leaner
  still but forces `ANTHROPIC_API_KEY` (never reads OAuth), so it's unusable with
  the subscription token. `CLAUDE_MODEL` overrides the model (default `sonnet`);
  isolate a run with `CHINESE_CACHE_DIR=…`.
- A/B on 明 (`日`+`月`): identical structure, fully audit-clean both ways; Claude's
  interpretations were richer (sun+moon→clear lucidity; moon→month via the lunar
  cycle). Minor Claude quirks: occasionally recurses one extra referenced char,
  and may omit the traditional clause on an all-identical sentence (cosmetic).

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
  `collapse_identical_parens(line, empty_slots=False)` in `write_card_md`,
  applied to ALL lines incl. examples. **A character is annotated ONLY when its
  traditional form differs** from the simplified: differing chars are wrapped
  individually as `字(繁)`, identical chars are left BARE (`糸(糸)`→`糸`,
  `小学(小學)`→`小学(學)`, `我回答是的(我回答是的)`→`我回答是的`). Each differing char is
  wrapped on its own (never a multi-char `(…)`) so the ruby stays per-character
  and the malformed-parens audit (multi-char clause annotations) doesn't trip.
  (Earlier versions used empty `字( )` ruby slots on identical chars; that
  parenthesised every character and was removed.)

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

## Glyph progressions (`lib/output/chinese/glyph.py`)
- `build_progression(char)` scrapes the "Historical forms" table from Wiktionary
  and composites a labeled strip to `output/chinese/media/glyph<cp>.png`. It runs
  **inline during normal generation** — `generate_card_content` builds the image
  for each freshly-generated single char; the renderer emits `![](@media/...)` for
  any char whose image exists. Best-effort: failures/no-table return None (never
  break generation); no-table chars are remembered in `media/.no_table.txt`.
- **Wikimedia needs a policy-compliant User-Agent** (project URL + contact) or
  `upload.wikimedia.org` 429s every image regardless of rate.
- `scripts/build_all_glyphs.py` bulk-backfills the library for existing cards;
  `scripts/glyph_progression.py` is a one-off CLI + Mochi attach. `mochi_sync`
  uploads every `@media` image a card references as a per-card attachment.

## Misc
- Don't commit secrets. Commit/push only when asked. Reusable interactive flows
  live as slash commands in `.claude/commands/` (`/generate-flashcards`,
  `/class-vocab-from-teams`).
