---
description: Turn an attached vocab image into a flashcard batch and recursively generate the cards
argument-hint: (attach a vocab-list image when invoking)
---

# Generate flashcards from an image

You are turning an attached image of a Chinese vocabulary list into a new flashcard
batch, then running the generator (which recurses into sub-words and components).

Work through the steps **in order**. Steps 1–4 are interactive — ask the user and
wait for an answer before moving on. Do not skip ahead or assume answers.

## Inputs

- An **image** is attached to the message that invoked this command. It is a
  vocabulary list — typically rows of `汉字 / pīnyīn / part-of-speech / English`,
  and sometimes a trailing "Proper Name" section. If no image is attached, stop and
  ask the user to attach one.
- `$ARGUMENTS` may contain hints (e.g. a folder id or "book"/"class"). Honor them if
  present, but still confirm via the questions below.

## Step 0 — OCR the image into CSV (do this first, silently)

Read the attached image and transcribe **every** vocab row (including any
"Proper Name" rows) into CSV with this exact header and column order:

```
Chinese,Pinyin,English
```

Rules, to match the existing corpus (see `output/chinese/**/input/-input.raw.txt`):

- **Chinese**: the hanzi exactly as shown. Keep parenthetical/optional parts as
  written (e.g. `零（下）`).
- **Pinyin**: lowercase with tone marks. Join syllables of a single word
  (`jiāyóu`); separate distinct words with a space (`xià xuě`). Capitalize proper
  nouns (`Guǎngzhōu`, `Āijí`).
- **English**: the gloss only. **Drop the part-of-speech** column (`v.`, `n.`,
  `adj.`, …) — it is not stored. Join multiple senses with `; `
  (`to pat; to beat; to take (a picture)`).
- One row per entry. Do not renumber, sort, or dedupe — preserve the image's order.

Show the user the transcribed CSV and ask them to confirm or correct it before
writing anything to disk.

## Step 1 — Class or not class?

Ask: **"Is this for class, or not class (general)?"**

- **class**  → batch lives under `output/chinese/class/<id>/`
- **not class** → batch lives under `output/chinese/general/daily/<id>/`

## Step 2 — Class number (the batch id)

Ask the user for the **batch id** (what they call the "class number").

By convention these are dates in `M-D-YY` format (e.g. `1-8-26`), but some general
batches are numeric (e.g. `1000`). Whatever the user gives, use it verbatim as the
folder name.

## Step 3 — Suggest the next id

Before the user answers Step 2, **list the existing sibling folders** so they can
pick the next one, and propose a default:

- class → `ls output/chinese/class/`
- not class → `ls output/chinese/general/daily/`

Suggest a sensible next id:

- If the existing ids look like `M-D-YY` dates, suggest **today's date** in that
  format (today is available from the environment; e.g. `2026-06-13` → `6-13-26`).
- If they look numeric, suggest the **max + a round increment**.

Present the existing ids and your suggestion, and let the user confirm or override.

## Step 3b — (class only) book or in-class?

If Step 1 was **class**, a class id has two sub-batches:
`output/chinese/class/<id>/book/` and `output/chinese/class/<id>/class/`.
Ask which this image is (default **book** for a textbook vocabulary page). The image
goes in that subfolder. For **not class**, there is no sub-batch.

## Step 4 — Scaffold and generate

1. Resolve the target **input folder**:
   - class: `output/chinese/class/<id>/<book|class>/input/`
   - not class: `output/chinese/general/daily/<id>/input/`

2. If a `-input.raw.txt` already exists there with content, **stop and confirm**
   with the user before overwriting (the generator skips already-built cards, so
   appending vs. replacing matters).

3. Create the folder and write two files:
   - `<input>/-input.raw.txt` — the confirmed CSV from Step 0.
   - `<input>/-config.json`:
     ```json
     {
       "output_type": "chinese",
       "raw_input_file": "-input.raw.txt",
       "output_dir": "../output"
     }
     ```

4. Run the generator on that config (it parses input, then recursively builds
   `.md` cards for each word plus its sub-words and components). Prefer the venv;
   fall back to `python3`. Set up the venv with `make setup` first if it's missing.

   ```bash
   .venv/bin/python generate.py --config <input>/-config.json --verbose
   ```

   Stream the output. The generator skips existing `.md` files, halts on the first
   BLOCKED item with a reason, and is safe to re-run to resume.

5. When it finishes, report: the target folder, how many cards were written
   (`ls <.../output>/*.md | wc -l`), and any BLOCKED/skipped items that need a
   re-run or manual attention.

## Notes

- Requires `OPENAI_API_KEY` in `.env` (auto-loaded). If the run fails on auth, tell
  the user to set it.
- Don't commit anything unless the user asks.
