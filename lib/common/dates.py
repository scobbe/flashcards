"""Batch-id date handling.

Batch folders under ``output/chinese/class/`` and ``output/chinese/general/daily/``
are named by date in **``YY-MM-DD``** order (year-month-day, zero-padded), e.g.
``25-12-27`` = 27 December 2025. This big-endian, zero-padded form sorts
chronologically as plain text, so a lexical ``ls`` / ``sorted()`` is already in
ascending date order. (Older batches used American ``M-D-YY``; the corpus was
converted.) Some general batches are numeric (e.g. ``1000``) rather than dates.

Use :func:`parse_batch_date` to turn an id into a sortable date and
:func:`sort_batch_ids` to order a list of ids by ascending real date (numeric /
non-date ids sort last).
"""
from __future__ import annotations

import re
from datetime import date
from typing import Iterable, List, Optional

_DATE_RE = re.compile(r"^(\d{2})-(\d{2})-(\d{2})$")


def parse_batch_date(batch_id: str) -> Optional[date]:
    """Parse a ``YY-MM-DD`` batch id into a ``date`` (``20YY``).

    Returns ``None`` if the id is not a YY-MM-DD date (e.g. a numeric batch id,
    or an out-of-range month/day)."""
    m = _DATE_RE.match((batch_id or "").strip())
    if not m:
        return None
    yy, month, day = (int(g) for g in m.groups())
    try:
        return date(2000 + yy, month, day)
    except ValueError:
        return None


def to_batch_id(d: date) -> str:
    """Format a ``date`` as a ``YY-MM-DD`` batch id (zero-padded)."""
    return f"{d.year % 100:02d}-{d.month:02d}-{d.day:02d}"


def today_id() -> str:
    """Today's date as a ``YY-MM-DD`` batch id."""
    return to_batch_id(date.today())


def sort_batch_ids(ids: Iterable[str]) -> List[str]:
    """Sort batch ids by ascending real date; non-date ids sort last (natural).

    For valid YY-MM-DD ids this matches a plain lexical sort, but it also keeps
    numeric / malformed ids in a sensible order."""
    far = date(9999, 12, 31)
    return sorted(ids, key=lambda b: (parse_batch_date(b) or far, b))
