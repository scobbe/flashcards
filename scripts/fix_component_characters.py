#!/usr/bin/env python3
import sys
import re
from pathlib import Path


def is_cjk_char(ch: str) -> bool:
    if not ch or len(ch) != 1:
        return False
    # Include ideographic number zero explicitly
    if ch == "〇":
        return True
    code = ord(ch)
    if 0x3400 <= code <= 0x9FFF:
        return True
    if 0xF900 <= code <= 0xFAFF:
        return True
    if 0x2E80 <= code <= 0x2EFF:
        return True
    if 0x2F00 <= code <= 0x2FDF:
        return True
    if 0x20000 <= code <= 0x2EBEF:
        return True
    if 0x30000 <= code <= 0x3134F:
        return True
    return False


RADICAL_VARIANT_TO_PRIMARY = {
    "钅": "金",
    "氵": "水",
    "忄": "心",
    "扌": "手",
    "纟": "糸",
    "艹": "艸",
    "饣": "食",
    "讠": "言",
    "阝": "阜",
}


def map_variant(ch: str) -> str:
    return RADICAL_VARIANT_TO_PRIMARY.get(ch, ch)


def extract_description(lines) -> str:
    for line in lines:
        if "**description:**:" in line:
            try:
                return line.split("**description:**:", 1)[1].strip()
            except Exception:
                continue
    return ""


def transform_md_text(text: str) -> str:
    lines = text.splitlines()
    desc = extract_description(lines)
    if not desc:
        return text
    # Collect all unique CJK characters from description
    chars = []
    seen = set()
    for ch in desc:
        if is_cjk_char(ch):
            mapped = map_variant(ch)
            if mapped not in seen:
                seen.add(mapped)
                chars.append(mapped)

    # Rewrite all component_characters sections anywhere in the file
    out_lines = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if re.match(r"^\s*- \*\*component characters:\*\*\s*$", line):
            # write header as-is
            out_lines.append(line)
            i += 1
            # Determine header indent
            m = re.match(r"^(\s*)- \\*\\*component characters:.*$", line)
            header_indent = len(m.group(1)) if m else 0
            # skip existing list items more indented than header
            while i < len(lines):
                cur = lines[i]
                m2 = re.match(r"^(\s*)- ", cur)
                if not m2:
                    break
                if len(m2.group(1)) <= header_indent:
                    break
                i += 1
            # insert our synthesized list
            sub_indent = " " * (header_indent + 2)
            for ch in chars:
                out_lines.append(sub_indent + "- " + ch)
            # do not increment i here; outer loop continues at current i
            continue
        out_lines.append(line)
        i += 1
    return "\n".join(out_lines) + ("\n" if not text.endswith("\n") else "")


def process_dir(root: Path) -> int:
    count = 0
    for p in sorted(root.glob("*.md")):
        if p.name == "-output.md":
            continue
        try:
            old = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        new = transform_md_text(old)
        if new != old:
            p.write_text(new, encoding="utf-8")
            count += 1
    return count


def main(argv=None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    target = Path(argv[0]).resolve() if argv else Path.cwd()
    if target.is_dir():
        changed = process_dir(target)
        print(f"[ok] Updated component characters in {changed} file(s) under {target}")
        return 0
    print("usage: fix_component_characters.py /absolute/path/to/folder", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())


