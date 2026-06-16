---
description: Turn a day's Chinese-class Teams chat into a flashcard batch and generate the cards
argument-hint: [chat name] [date e.g. 26-06-15]  (both optional)
---

# Generate class flashcards from a Teams lesson

Pull the vocabulary your teacher sent in a Microsoft Teams lesson chat, turn it
into a flashcard batch, and generate the cards (recursing into components).

The chat is your **personal** Teams, read from the local cache via
`scripts/teams_personal.py` (Graph has no personal-Teams API). Work through the
steps in order; steps 1–4 are interactive — ask and wait for an answer.

## Inputs
- `$ARGUMENTS` may contain a chat name and/or a date id. Honor them if present,
  but still confirm via the questions below.
- Default chat: **Quentin Luan**. Default date: **today**.

## Step 0 — Pull the lesson messages (do this first)

Run the reader and look at the target day's messages:

```bash
.venv/bin/python scripts/teams_personal.py messages --chat "<name>" --limit 600 | grep "<YYYY-MM-DD>"
```

(`<name>` defaults to "Quentin"; `<YYYY-MM-DD>` is the lesson date, e.g.
`2026-06-15`.) If nothing shows for the date, the desktop Teams app hasn't
cached it — tell the user to open that chat in the new Teams app and scroll, then
retry. If `messages` returns the wrong thread, there may be more than one chat
with that person; `list-chats` shows them.

### Identifying the real lesson (important)
When a chat is freshly opened, Teams re-caches the **entire history** with every
message stamped at the **same** sync minute (e.g. fifty messages all at
`20:35`). That block is NOT one day's lesson. The actual live lesson is the run
of messages with **distinct, spaced timestamps** on the target date
(e.g. `18:11 … 18:38`). Use that run; ignore a large same-timestamp block unless
the user explicitly wants the full history.

## Step 0b — Extract the vocabulary

The teacher's messages look like `世界 shi4 jie4`, `闭嘴 bi4 zui3`, `旧 / 老`,
`关 / 闭`, sometimes with a separate English line (`to win`, `support`). From the
lesson run, extract the **Chinese vocab words**:
- Keep the hanzi; drop the trailing numbered-pinyin annotation and any
  English-only / greeting-only lines (`晚上好`, `to win`).
- Split `X / Y` lines into separate words (`旧 / 老` → `旧`, `老`).
- Skip pure grammar patterns with placeholders (`V1 着 V2`, `对…来说`,
  `是……的`) unless the user wants them.
- De-dupe. Provide tone-marked pinyin and a short English gloss for each
  (you know these; correct any obvious teacher typos).

Show the user the extracted CSV (`Chinese,Pinyin,English`) and have them confirm
or edit before writing anything.

## Step 1 — Class or book?
Class lessons go in the **`class`** subfolder. Ask to confirm (default `class`;
`book` is for the textbook vocab covered separately).

## Step 2 — Batch id (date)
Ask for the batch id in **`YY-MM-DD`** (year-month-day, zero-padded;
e.g. `26-06-15` = 15 June 2026). Default to the lesson date. List existing ids,
sorted by ascending date, so they can confirm:
`.venv/bin/python scripts/list_batches.py output/chinese/class`.

## Step 3 — Scaffold and generate
1. Target input folder: `output/chinese/class/<id>/<class|book>/input/`.
2. If a `-input.raw.txt` already exists there with content, confirm before
   overwriting.
3. Write `-input.raw.txt` (the confirmed CSV) and `-config.json`:
   ```json
   { "output_type": "chinese", "raw_input_file": "-input.raw.txt", "output_dir": "../output" }
   ```
4. Generate:
   ```bash
   .venv/bin/python generate.py --config <input>/-config.json --verbose
   ```
   The fixed parser chunks long lists and refuses a short/truncated parse, so it
   won't silently drop words. Report cards written and any BLOCKED items.

## Step 4 — (optional) Sync to Mochi
Ask if they want it in Mochi. If yes:
- Ensure a deck exists for `class/<id>/<class|book>` (create subdecks under the
  `<id>` deck if needed, mirroring the other dates), add the mapping to
  `scripts/mochi_sync.py`, then:
  ```bash
  MOCHI_API_KEY=$(python -c "import json;print(json.load(open('$HOME/.claude.json'))['mcpServers']['mochi']['env']['MOCHI_API_KEY'])") \
    python scripts/mochi_sync.py --apply --only "<id>/<class|book>"
  ```
  Cards are matched by headword and updated in place (review history preserved).

## Notes
- Read-only: only chats cached locally by the new Teams app are available.
- Don't commit unless the user asks.
