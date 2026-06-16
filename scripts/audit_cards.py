#!/usr/bin/env python3
"""Audit generated flashcards for compliance + vacuous explanations.

Deterministic checks by default (fast, no API); add --llm for an LLM pass that
judges each interpretation for genuine vacuousness. Exits non-zero if any
errors (not warnings) are found, so it can gate CI / a generation run.

    python scripts/audit_cards.py                       # all batches
    python scripts/audit_cards.py output/chinese/class/26-06-17/book/output
    python scripts/audit_cards.py --llm                 # + LLM vacuousness judge
    python scripts/audit_cards.py --errors-only
"""
import argparse
import glob
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from lib.common import _load_env_file  # noqa: E402
from lib.output.chinese.audit import audit_output_dir, format_report  # noqa: E402


def _all_output_dirs():
    dirs = set()
    for cfg in glob.glob(str(ROOT / "output/chinese/**/input/-config.json"), recursive=True):
        out = Path(cfg).parent.parent / "output"
        if out.exists() and any(p.name[0].isdigit() for p in out.glob("*.md")):
            dirs.add(out)
    return sorted(dirs, key=str)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("dirs", nargs="*", help="batch output dir(s); default: all batches")
    ap.add_argument("--llm", action="store_true", help="also LLM-judge interpretations for vacuousness")
    ap.add_argument("--errors-only", action="store_true", help="suppress warnings")
    args = ap.parse_args(argv)
    if args.llm:
        _load_env_file()

    dirs = [Path(d) for d in args.dirs] if args.dirs else _all_output_dirs()
    all_issues = []
    for d in dirs:
        issues = audit_output_dir(d, repo_root=ROOT, llm=args.llm)
        if args.errors_only:
            issues = [i for i in issues if i.severity == "error"]
        rel = d.relative_to(ROOT) if d.is_absolute() else d
        if issues:
            print(f"\n=== {rel} ===")
            print(format_report(issues))
        all_issues += issues

    errs = sum(1 for i in all_issues if i.severity == "error")
    warns = sum(1 for i in all_issues if i.severity == "warn")
    print(f"\nTOTAL: {errs} error(s), {warns} warning(s) across {len(dirs)} batch(es)")
    return 1 if errs else 0


if __name__ == "__main__":
    raise SystemExit(main())
