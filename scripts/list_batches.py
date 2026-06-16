#!/usr/bin/env python3
"""List existing batch ids in a directory, sorted by ascending real date.

Date ids are YY-MM-DD (see lib/common/dates). Numeric / non-date ids sort last.
Used by the flashcard slash commands so the user picks the next id from a
chronologically-ordered list.

    python scripts/list_batches.py output/chinese/class
    python scripts/list_batches.py output/chinese/general/daily
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib.common.dates import sort_batch_ids, parse_batch_date, today_id  # noqa: E402


def main(argv=None):
    argv = argv or sys.argv[1:]
    if not argv:
        print("usage: list_batches.py <dir>", file=sys.stderr)
        return 2
    d = Path(argv[0])
    ids = [p.name for p in d.iterdir() if p.is_dir()] if d.exists() else []
    for b in sort_batch_ids(ids):
        dt = parse_batch_date(b)
        print(f"{b}\t{dt.isoformat() if dt else ''}")
    print(f"\ntoday (YY-MM-DD): {today_id()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
