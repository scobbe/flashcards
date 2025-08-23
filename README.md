# Flashcards CLI

Generate Chinese flashcards from raw learning text using Wiktionary and OpenAI.

## Prerequisites
- Python 3.9+
- OpenAI API key

## Setup
1) Install dependencies:

```bash
python3 -m pip install -r requirements.txt
```

2) Create a `.env` in project root:

```env
OPENAI_API_KEY=sk-...
# Optional model override
OPENAI_MODEL=gpt-4o-mini
```

## Usage
- Create instance directories under `output/`, each with an `input.txt`:

```bash
mkdir -p output/book
cp your_input.txt output/book/input.txt
```
- Run generator (streams progress, skips existing `.md` files, halts on first error):

```bash
.venv/bin/python generate.py --verbose
```

### Makefile shortcuts
- Setup venv + deps: `make setup`
- Run generator via Makefile:

```bash
make generate
```

## Output
- Per-word files: `<HEADWORD>.md` in each instance directory under `output/`.

## Behavior
- Automatically creates/uses `extracted.txt` in each instance to list vocab; edit it to change the processing set/order.
- Skips any vocab that already has `<HEADWORD>.md` in the instance directory.
- Recurses for multi‑character words: writes parent, subword character cards, and component cards until no more named components.
- Halts on the first BLOCKED with a detailed reason; re‑run to resume (completed files are skipped).
- Pronunciation is Pinyin‑only (tone marks), multiple readings separated by ` / `.
- Examples are formatted as `ZH (pinyin) - EN`.

## Notes
- `.env` is auto-loaded on startup (no manual export needed).
- The tool calls OpenAI for judgment steps (headword extraction and single-headword field extraction), then validates and writes Markdown following a fixed schema.
