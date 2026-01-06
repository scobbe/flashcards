"""Card writing and rendering functions."""

import csv
import json as _json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from lib.schema.written import BACK_SCHEMA
from lib.schema.base import CardField

from lib.common.utils import is_cjk_char, _clean_value
from lib.output.schema_utils import _field_name_to_key
from lib.output.etymology import _map_radical_variant_to_primary


def read_parsed_input(parsed_path: Path) -> List[Tuple[str, str, str, str, str, str]]:
    """Read parsed input CSV or txt file."""
    rows: List[Tuple[str, str, str, str, str, str]] = []
    if parsed_path.suffix.lower() == ".csv":
        with parsed_path.open("r", encoding="utf-8") as f:
            reader = csv.reader(f)
            for rec in reader:
                if not rec:
                    continue
                simp = rec[0].strip() if len(rec) > 0 else ""
                trad = rec[1].strip() if len(rec) > 1 else simp
                pin = rec[2].strip() if len(rec) > 2 else ""
                eng = rec[3].strip() if len(rec) > 3 else ""
                phrase = rec[4].strip() if len(rec) > 4 else ""
                rel = rec[5].strip() if len(rec) > 5 else ""
                if simp:
                    rows.append((simp, trad, pin, eng, phrase, rel))
    else:
        for line in parsed_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            if "." in line:
                _, rest = line.split(".", 1)
            else:
                rest = line
            pieces = [p.strip() for p in rest.split(",")]
            simp = pieces[0] if len(pieces) > 0 else rest.strip()
            trad = pieces[1] if len(pieces) > 1 else simp
            pin = pieces[2] if len(pieces) > 2 else ""
            eng = pieces[3] if len(pieces) > 3 else ""
            rel = pieces[4] if len(pieces) > 4 else ""
            if simp:
                rows.append((simp, trad, pin, eng, "", rel))
    return rows


def _extract_card_info(md_path: Path) -> Tuple[str, str, str, str]:
    """Extract english, traditional, simplified, pinyin from a markdown card file.
    
    Returns (english, traditional, simplified, pinyin) tuple.
    """
    if not md_path.exists():
        return "", "", "", ""
    try:
        content = md_path.read_text(encoding="utf-8")
        english = ""
        traditional = ""
        simplified = ""
        pinyin = ""
        
        for line in content.split("\n"):
            if line.startswith("## "):
                english = line[3:].strip()
            elif line.startswith("- **traditional:**"):
                traditional = line.split(":**", 1)[1].strip() if ":**" in line else ""
            elif line.startswith("- **simplified:**"):
                simplified = line.split(":**", 1)[1].strip() if ":**" in line else ""
            elif line.startswith("- **pronunciation:**"):
                pinyin = line.split(":**", 1)[1].strip() if ":**" in line else ""
        
        return english, traditional, simplified, pinyin
    except Exception:
        pass
    return "", "", "", ""


def _build_breadcrumbs(out_dir: Path, word: str) -> Tuple[List[str], List[Tuple[str, str, str, str]]]:
    """Build English and Chinese breadcrumb chains from the word/filename.
    
    For word like "1.得.寸.尊.酋", returns ancestors only (excludes current character):
    - english_crumbs: ["structural particle", "inch", "honor"]  (not including "wine")
    - chinese_crumbs: [(simplified, traditional, pinyin, english), ...] for each ancestor
    """
    parts = word.split(".")
    if len(parts) < 3:  # Need at least "1.char1.char2" for breadcrumbs
        return [], []
    
    # Extract CJK characters from the chain (skip the numeric prefix)
    all_chinese: List[str] = []
    for p in parts[1:]:
        if len(p) == 1 and is_cjk_char(p):
            all_chinese.append(p)
    
    if len(all_chinese) < 2:
        return [], []
    
    # Exclude the current character (last one) - only show ancestors
    ancestor_chars = all_chinese[:-1]
    
    # Build crumbs by looking up each ancestor file
    english_crumbs: List[str] = []
    chinese_crumbs: List[Tuple[str, str, str, str]] = []  # (simplified, traditional, pinyin, english)
    prefix = parts[0]  # e.g., "1"
    
    for i, ch in enumerate(ancestor_chars):
        if i == 0:
            # First character - look at the base file
            md_path = out_dir / f"{prefix}.{ch}.md"
        else:
            # Subsequent characters - build the chain path
            chain = ".".join(ancestor_chars[:i+1])
            md_path = out_dir / f"{prefix}.{chain}.md"
        
        eng, trad, simp, pin = _extract_card_info(md_path)
        english_crumbs.append(eng if eng else ch)
        chinese_crumbs.append((simp or ch, trad or ch, pin or "", eng or ""))
    
    return english_crumbs, chinese_crumbs


def write_simple_card_md(
    out_dir: Path,
    word: str,
    english: str,
    traditional: str,
    simplified: str,
    pinyin: str,
    relation: str,
    back_fields: Optional[Dict[str, Dict[str, str] | str]] = None,
    verbose: bool = False,
) -> Path:
    """Write a flashcard markdown file."""
    md_path = out_dir / f"{word}.md"
    parts: List[str] = []
    
    # Build breadcrumbs for sub-component cards
    english_breadcrumbs: List[str] = []
    chinese_breadcrumbs: List[Tuple[str, str, str, str]] = []  # (simplified, traditional, pinyin, english)
    
    # Custom header layout for sub-word and sub-component relations
    rel = relation.strip()
    parent_english = ""
    rel_type = ""
    if rel:
        rel_norm = rel.replace("subword", "sub-word").replace("subcomponent", "sub-component")
        if rel_norm.startswith("sub-word of ") or rel_norm.startswith("sub-component of "):
            rel_type = "sub-word" if rel_norm.startswith("sub-word of ") else "sub-component"
            q1 = rel_norm.find('"')
            q2 = rel_norm.rfind('"')
            if q1 != -1 and q2 != -1 and q2 > q1:
                parent_english = rel_norm[q1 + 1 : q2]
            
            # Build breadcrumbs for sub-components
            english_breadcrumbs, chinese_breadcrumbs = _build_breadcrumbs(out_dir, word)
            
            # If no breadcrumbs from filename chain, try to find parent file by English name
            if not english_breadcrumbs and parent_english:
                # Search for a file in the same directory with matching English heading
                for candidate in out_dir.glob("*.md"):
                    if candidate.name.startswith("-"):
                        continue
                    eng, trad, simp, pin = _extract_card_info(candidate)
                    if eng == parent_english:
                        english_breadcrumbs = [eng]
                        chinese_breadcrumbs = [(simp or "", trad or "", pin or "", eng or "")]
                        break
            
            parts.append(f"## {english}")
            # Add English breadcrumbs with appropriate label based on rel_type
            # Use hyphens: "sub-component of" or "sub-word of"
            from_label = "*sub-component of*" if rel_type == "sub-component" else "*sub-word of*"
            if english_breadcrumbs and len(english_breadcrumbs) >= 1:
                parts.append(from_label)
                for i, eng in enumerate(english_breadcrumbs):
                    parts.append(f"{i+1}. {eng}")
            elif parent_english:
                # Fallback to just parent if no breadcrumbs
                parts.append(from_label)
                parts.append(f"1. {parent_english}")
        else:
            parts.append(f"## {english}")
            parts.append(f"### {rel_norm}")
    else:
        parts.append(f"## {english}")
    parts.append("---")

    # Helper to render schema label with placeholders
    def render_label(name: str) -> str:
        label = name.replace("{traditional}", traditional).replace("{simplified}", simplified)
        return label

    # Map schema fields by key
    name_by_key: Dict[str, str] = {}
    for f in BACK_SCHEMA.fields:
        k = _field_name_to_key(f.name)
        name_by_key[k] = f.name

    # Print core required fields
    for base_key in ("traditional", "simplified", "pronunciation", "definition"):
        label = render_label(name_by_key.get(base_key, base_key))
        if base_key == "definition":
            bf_def = ""
            if isinstance(back_fields, dict):
                v = back_fields.get("definition")
                if isinstance(v, str):
                    bf_def = v.strip()
            value = english or bf_def
        elif base_key == "traditional":
            value = traditional
        elif base_key == "simplified":
            value = simplified
        else:
            bf_pin = ""
            if isinstance(back_fields, dict):
                v = back_fields.get("pronunciation")
                if isinstance(v, str):
                    bf_pin = v.strip()
            value = pinyin or bf_pin
        parts.append(f"- **{label}:** {value}")

        # Add Chinese breadcrumbs after definition for sub-components
        # Hierarchical format with character, pinyin, and definition on separate lines
        if base_key == "definition" and chinese_breadcrumbs and len(chinese_breadcrumbs) >= 1:
            parts.append("- **breadcrumbs:**")
            for simp, trad, pin, eng_def in chinese_breadcrumbs:
                # Chinese character with traditional
                if trad and trad != simp:
                    parts.append(f"  - {simp}({trad})")
                else:
                    parts.append(f"  - {simp}")
                # Pinyin on indented line
                if pin:
                    parts.append(f"    - {pin}")
                # English definition on indented line
                if eng_def:
                    parts.append(f"    - {eng_def}")

    rendered_keys = {"traditional", "simplified", "pronunciation", "definition", "breadcrumbs"}

    # AI-derived fields from schema
    if back_fields:
        ctx = {"traditional": traditional, "simplified": simplified}

        def render_field(field: CardField, value: object, indent: int = 0) -> None:
            if callable(getattr(field, "skip_if", None)) and field.skip_if(ctx):
                return
            label = render_label(field.name)
            pad = "  " * indent
            if field.field_type == "section":
                parts.append(f"{pad}- **{label}:**")
                section_val = value if isinstance(value, dict) else {}
                for ch in field.children or []:
                    ck = _field_name_to_key(ch.name)
                    render_field(ch, section_val.get(ck), indent + 1)
                return
            if field.ai_prompt is None and field.default_provider is None:
                return
            if field.field_type == "sublist":
                items = value if isinstance(value, list) else []
                try:
                    max_items = getattr(field, "max_items", None)
                except Exception:
                    max_items = None
                if isinstance(max_items, int) and max_items > 0:
                    items = items[:max_items]
                try:
                    fk = _field_name_to_key(field.name)
                except Exception:
                    fk = ""
                if fk == "component_characters" and not items:
                    try:
                        et = back_fields.get("etymology") if isinstance(back_fields, dict) else None
                        desc_any = et.get("description") if isinstance(et, dict) else ""
                        synthesized: List[str] = []
                        for ch in str(desc_any):
                            if len(ch) == 1 and is_cjk_char(ch):
                                mapped = _map_radical_variant_to_primary(ch)
                                if mapped not in synthesized:
                                    synthesized.append(mapped)
                        items = synthesized
                    except Exception:
                        pass
                parts.append(f"{pad}- **{label}:**")
                if items:
                    for item in items:
                        item_str = str(item)
                        # Hierarchical format for items with "Chinese: pinyin; english" pattern
                        # Used by contemporary_usage and other sublists
                        if ": " in item_str and "; " in item_str:
                            chinese_part, rest = item_str.split(": ", 1)
                            pinyin_part, english_part = rest.split("; ", 1)
                            parts.append(f"{pad}  - {chinese_part}")
                            parts.append(f"{pad}    - {pinyin_part}")
                            if english_part:
                                parts.append(f"{pad}    - {english_part}")
                        # Hierarchical format for component_characters: "爻 (yáo, "trigram lines")"
                        elif fk == "component_characters" and " (" in item_str and item_str.endswith(")"):
                            # Parse format: Chinese (pinyin, "english")
                            import re
                            match = re.match(r'^(.+?)\s+\(([^,]+),\s*"([^"]+)"\)$', item_str)
                            if match:
                                chinese_part = match.group(1)
                                pinyin_part = match.group(2).strip()
                                english_part = match.group(3).strip()
                                parts.append(f"{pad}  - {chinese_part}")
                                parts.append(f"{pad}    - {pinyin_part}")
                                parts.append(f"{pad}    - {english_part}")
                            else:
                                parts.append(f"{pad}  - {item_str}")
                        else:
                            # Simple bullet for items without the pattern
                            parts.append(f"{pad}  - {item_str}")
                else:
                    fallback = getattr(field, "empty_fallback", None) or ""
                    if fk == "component_characters":
                        simp_len = len((ctx.get("simplified") or ""))
                        trad_len = len((ctx.get("traditional") or ""))
                        is_compound = max(simp_len, trad_len) > 1
                        if is_compound:
                            fallback = "None, compound word"
                    if fallback:
                        parts.append(f"{pad}  - {fallback}")
                return
            if isinstance(value, str) and value.strip():
                clean = _clean_value(value.strip())
                parts.append(f"{pad}- **{label}:** {clean}")

        for f in BACK_SCHEMA.fields:
            k = _field_name_to_key(f.name)
            if k in rendered_keys:
                continue
            v = back_fields.get(k) if isinstance(back_fields, dict) else None
            render_field(f, v, indent=0)
    parts.append("%%%")
    content = "\n".join(parts) + "\n"
    md_path.write_text(content, encoding="utf-8")
    if verbose:
        print(f"[file] Created: {md_path.name}")
    return md_path


def render_grammar_folder_cards(folder: Path, verbose: bool = False) -> int:
    """Render grammar cards from parsed CSV."""
    path = folder / "-input.parsed.grammar.csv"
    if not path.exists():
        return 0
    written = 0
    with path.open("r", encoding="utf-8") as f:
        reader = csv.reader(f)
        for idx, row in enumerate(reader, start=1):
            try:
                desc = (row[0] if len(row) > 0 else "").strip()
                usage_cn = (row[1] if len(row) > 1 else "").strip()
                ex_json = (row[2] if len(row) > 2 else "[]").strip()
                try:
                    examples = _json.loads(ex_json)
                except Exception:
                    examples = []
                if not isinstance(examples, list):
                    examples = []
            except Exception:
                continue
            if not desc:
                continue
            base = f"G{idx}.grammar"
            md_path = folder / f"{base}.md"
            parts: List[str] = []
            parts.append(f"## {desc}")
            parts.append(f"### grammar rule")
            parts.append("---")
            parts.append(f"- **description:** {desc}")
            parts.append(f"- **usage in Chinese:** {usage_cn}")
            parts.append(f"- **examples:**")
            for ex in examples:
                parts.append(f"  - {str(ex)}")
            parts.append("%%%")
            content = "\n".join(parts) + "\n"
            md_path.write_text(content, encoding="utf-8")
            written += 1
            if verbose:
                print(f"[ok] Grammar card: {md_path.name}")
    # Append to -output.md
    try:
        output_md = folder / "-output.md"
        md_files = [p for p in sorted(folder.glob("*.md")) if p.name != "-output.md"]
        parts2: List[str] = []
        for p in md_files:
            try:
                parts2.append(p.read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                continue
        output_md.write_text("\n\n".join(parts2) + ("\n" if parts2 else ""), encoding="utf-8")
        if verbose:
            print(f"[ok] Wrote {output_md.name} ({len(parts2)} files)")
    except Exception:
        pass
    return written


def render_grammar_folder(folder: Path, verbose: bool = False) -> None:
    """Render grammar folder."""
    render_grammar_folder_cards(folder, verbose=verbose)

