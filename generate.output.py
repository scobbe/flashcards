import argparse
import os
import sys
import time
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup  # type: ignore
from openai_helper import OpenAIClient
from schema import BACK_SCHEMA, CardField


def log_debug(enabled: bool, message: str) -> None:
    if enabled:
        print(f"[debug] {message}")


def read_parsed_input(parsed_path: Path) -> List[Tuple[str, str, str, str, str]]:
    rows: List[Tuple[str, str, str, str, str]] = []
    if parsed_path.suffix.lower() == ".csv":
        import csv
        with parsed_path.open("r", encoding="utf-8") as f:
            reader = csv.reader(f)
            for rec in reader:
                if not rec:
                    continue
                simp = rec[0].strip() if len(rec) > 0 else ""
                trad = rec[1].strip() if len(rec) > 1 else simp
                pin = rec[2].strip() if len(rec) > 2 else ""
                eng = rec[3].strip() if len(rec) > 3 else ""
                rel = rec[4].strip() if len(rec) > 4 else ""
                if simp:
                    rows.append((simp, trad, pin, eng, rel))
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
                rows.append((simp, trad, pin, eng, rel))
    return rows


def wiktionary_url_for_word(word: str) -> str:
    # Use English Wiktionary which contains Chinese entries
    return f"https://en.wiktionary.org/wiki/{requests.utils.requote_uri(word)}"


def fetch_wiktionary_html_status(word: str, timeout: float = 20.0) -> Tuple[str, int]:
    url = wiktionary_url_for_word(word)
    try:
        resp = requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": "flashcards-script/1.0 (+https://example.local)"},
        )
        status = resp.status_code
        text = resp.text if resp.text is not None else ""
        return text, status
    except Exception:
        # Treat network errors as 0 status with empty body
        return "", 0


def sanitize_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    # Remove heavy or irrelevant sections to keep tokens small
    for tag in soup(["script", "style", "noscript", "footer", "nav", "header"]):
        tag.decompose()
    # Constrain very large tables and lists instead of dropping useful content (e.g., compounds)
    for tag in soup.find_all(["table"]):
        try:
            text_len = len(tag.get_text(" "))
        except Exception:
            text_len = 0
        if text_len > 20000:
            tag.decompose()
    for tag in soup.find_all(["ul", "ol"]):
        try:
            items = tag.find_all("li", recursive=False)
        except Exception:
            items = []
        if len(items) > 0:
            # Keep only the first N items to avoid token bloat but preserve examples/compounds
            keep_n = 50
            for li in items[keep_n:]:
                li.decompose()
    # Truncate extremely long pages safely
    text = str(soup)
    if len(text) > 150_000:
        text = text[:150_000]
    return text


def _clean_value(text: str) -> str:
    if not isinstance(text, str):
        return text
    # Strip control chars that can render as odd glyphs
    return "".join(ch for ch in text if (ch == "\n" or ch == "\t" or ord(ch) >= 32))


def is_cjk_char(ch: str) -> bool:
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


def section_header(word: str) -> str:
    return f"<!-- word: {word} -->\n<h1>{word}</h1>\n"


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _parse_component_english_map(description: str) -> Dict[str, str]:
    # Parse tokens like: X (pinyin, "english") and map single CJK char X -> english
    mapping: Dict[str, str] = {}
    if not isinstance(description, str) or not description:
        return mapping
    for m in re.finditer(r"([^\s()]+)\s*\([^)]*,\s*\"([^\"]+)\"\)", description):
        han = m.group(1)
        en = m.group(2).strip()
        if len(han) == 1 and is_cjk_char(han) and han not in mapping:
            mapping[han] = en
    return mapping


def _collect_components_from_back(back_fields: Dict[str, object]) -> List[str]:
    comps: List[str] = []
    if not isinstance(back_fields, dict):
        return comps
    et = back_fields.get("etymology")
    if isinstance(et, dict):
        # Prefer explicit components list if present (schema key normalized)
        raw = et.get("components_characters")
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, str) and len(item) == 1 and is_cjk_char(item) and item not in comps:
                    comps.append(item)
        if not comps:
            desc = et.get("description") if isinstance(et.get("description"), str) else ""
            english_map = _parse_component_english_map(str(desc))
            for ch in english_map.keys():
                if len(ch) == 1 and is_cjk_char(ch) and ch not in comps:
                    comps.append(ch)
    return comps


def _generate_component_subtree(
    out_dir: Path,
    prefix: str,
    ch: str,
    component_english: str,
    parent_english: str,
    model: Optional[str],
    verbose: bool,
    debug: bool,
    delay_s: float,
    visited: set,
    depth: int,
    max_depth: int = 5,
    comp_cache: Optional[Dict[str, object]] = None,
) -> None:
    if depth > max_depth:
        return
    if ch in visited:
        return
    visited.add(ch)

    word_id = f"{prefix}.{ch}"
    md_path = out_dir / f"{word_id}.md"
    if md_path.exists():
        if verbose:
            print(f"[skip] Component already exists: {md_path.name}")
        return
    # Prepare HTML for this component (cached by path)
    html_path = out_dir / f"{word_id}.input.html"
    if html_path.exists():
        combined_html = html_path.read_text(encoding="utf-8", errors="ignore")
        if verbose:
            print(f"[info] Using cached HTML for {word_id}")
    else:
        combined_sections: List[str] = []
        fetched_set: Dict[str, bool] = {}
        for form in [ch]:
            form = (form or "").strip()
            if not form or form in fetched_set:
                continue
            fetched_set[form] = True
            form_html, form_status = fetch_wiktionary_html_status(form)
            if verbose:
                print(f"[info] Wiktionary GET {form} -> {form_status}")
            if form_status == 200 and form_html:
                combined_sections.append(section_header(form) + sanitize_html(form_html))
            else:
                combined_sections.append(section_header(form))
            if delay_s > 0:
                time.sleep(delay_s)
        combined_html = "\n\n".join(combined_sections)
        html_path.write_text(combined_html, encoding="utf-8")
        if verbose:
            print(f"[ok] Wrote {html_path.name} ({len(combined_html)} bytes)")

    # Generate back fields for this component (with cache)
    back: Dict[str, object] | object
    if comp_cache is not None and ch in comp_cache:
        log_debug(debug, f"cache hit for component '{ch}'")
        back = comp_cache[ch]
    else:
        if verbose:
            print(f"[info] OpenAI back-fields for {word_id} (model={model or 'default'})")
        back = extract_back_fields_from_html(
            simplified=ch,
            traditional=ch,
            english=component_english,
            html=combined_html,
            model=model,
            verbose=verbose,
            parent_word=parent_english,
        )
        if comp_cache is not None and isinstance(back, dict):
            comp_cache[ch] = back
    # Try to get pinyin from back fields (may be empty); AI fills when not in CSV
    pin = ""
    if isinstance(back, dict):
        pv = back.get("pronunciation")
        if isinstance(pv, str) and pv.strip():
            pin = pv.strip()

    # Write the component markdown with relation header
    write_simple_card_md(
        out_dir,
        word_id,
        component_english,
        ch,
        ch,
        pin,
        f'sub-component of "{parent_english}"',
        back_fields=back,
    )
    if verbose:
        print(f"[ok] Component card for {word_id}")

    # Recurse into this component's own components
    comps = _collect_components_from_back(back if isinstance(back, dict) else {})
    if not comps:
        return
    desc = (
        back.get("etymology", {}).get("description")
        if isinstance(back, dict) and isinstance(back.get("etymology"), dict)
        else ""
    )
    english_map = _parse_component_english_map(str(desc))
    for sub_ch in comps:
        sub_eng = english_map.get(sub_ch, "")
        _generate_component_subtree(
            out_dir,
            prefix=word_id,
            ch=sub_ch,
            component_english=sub_eng,
            parent_english=component_english,
            model=model,
            verbose=verbose,
            debug=debug,
            delay_s=delay_s,
            visited=visited,
            depth=depth + 1,
            max_depth=max_depth,
            comp_cache=comp_cache,
        )
def _field_name_to_key(name: str) -> str:
    # Lowercase, strip parenthetical placeholders, replace spaces/hyphens with underscores
    key = name.lower()
    # Remove parenthetical placeholders like ({traditional})
    while True:
        start = key.find("(")
        end = key.find(")", start + 1)
        if start != -1 and end != -1:
            key = key[:start] + key[end + 1 :]
        else:
            break
    key = key.replace(" ", "_").replace("-", "_")
    key = key.replace("__", "_").strip(" _")
    return key


def _build_back_json_shape() -> str:
    # Include fields whose schema has an ai_prompt; include containers if any child has an ai_prompt
    lines: list[str] = ["{"]
    def add_field(field: CardField, indent: int = 2):
        key = _field_name_to_key(field.name)
        if field.children:
            sublines: list[str] = []
            for ch in field.children or []:
                if ch.ai_prompt is None:
                    continue
                ck = _field_name_to_key(ch.name)
                sublines.append(" " * (indent + 2) + f"\"{ck}\": string,")
            if not sublines:
                return
            lines.append(" " * indent + f"\"{key}\": {{")
            if sublines[-1].strip().endswith(","):
                sublines[-1] = sublines[-1].rstrip(",")
            lines.extend(sublines)
            lines.append(" " * indent + "},")
        else:
            if field.ai_prompt is None:
                return
            # Use field_type to choose primitive type
            if field.field_type == "sublist":
                lines.append(" " * indent + f"\"{key}\": [string, ...],")
            else:
                lines.append(" " * indent + f"\"{key}\": string,")

    for f in BACK_SCHEMA.fields:
        add_field(f)
    if lines[-1].strip().endswith(","):
        lines[-1] = lines[-1].rstrip(",")
    lines.append("}")
    return "\n".join(lines)


def _collect_guidelines() -> str:
    # Use ONLY ai_prompt texts from schema.
    bullets: list[str] = []
    def add_guidance(field: CardField, prefix: str = ""):
        key = _field_name_to_key(field.name)
        if field.ai_prompt:
            bullets.append(f"- {prefix}{key}: {field.ai_prompt}")
        for ch in field.children or []:
            add_guidance(ch, prefix=(prefix + key + ".") if prefix else (key + "."))
    for f in BACK_SCHEMA.fields:
        add_guidance(f)
    return "\n".join(bullets)


def _required_optional_keys() -> tuple[list[str], list[str]]:
    required: list[str] = []
    optional: list[str] = []
    def add_req_opt(field: CardField, prefix: str = ""):
        key = _field_name_to_key(field.name)
        if field.ai_prompt is not None:
            fq = f"{prefix}{key}" if prefix else key
            (required if field.required else optional).append(fq)
        for ch in field.children or []:
            next_prefix = f"{prefix}{key}." if (prefix or field.ai_prompt is not None) else ("" if not key else key + ".")
            # Always traverse children so section fields contribute their ai-prompted children
            add_req_opt(ch, prefix=next_prefix if next_prefix else "")
    for f in BACK_SCHEMA.fields:
        add_req_opt(f)
    return required, optional


def extract_back_fields_from_html(
    simplified: str,
    traditional: str,
    english: str,
    html: str,
    model: Optional[str],
    verbose: bool = False,
    parent_word: Optional[str] = None,
) -> Dict[str, Dict[str, str] | str]:
    client = OpenAIClient(model=model)
    trad_url = wiktionary_url_for_word(traditional or simplified)
    req, opt = _required_optional_keys()
    system = (
        "You generate back-of-card fields for a Chinese vocabulary flashcard. Output STRICT JSON ONLY matching this shape:\n"
        + _build_back_json_shape()
        + "\nRequired fields: "
        + ", ".join(req)
        + "\nOptional fields: "
        + ", ".join(opt)
        + "\nGuidance (from schema ai_prompts only):\n"
        + _collect_guidelines()
        + "\nHARD CONSTRAINTS:\n"
          "- Return ONLY raw JSON (no markdown, no commentary).\n"
          "- Adhere EXACTLY to field-level guidance from the schema.\n"
          "- If a required value cannot be sourced from the provided HTML (except simplification_rule), return an empty string.\n"
          "- Be concise. Do NOT add extra sentences, labels, or keys.\n"
          "- Do NOT invent facts not present in the HTML (except simplification_rule intuition).\n"
          "- Do NOT change field names or structure.\n"
          "- Use the provided Wiktionary HTML as the PRIMARY source; only the simplification rule may use general knowledge."
    )
    user = (
        "Headword (simplified): "
        + simplified
        + "\nHeadword (traditional): "
        + (traditional or simplified)
        + "\nEnglish gloss: "
        + english
        + "\nReference URL (traditional form): "
        + trad_url
        + "\n\n"
        + "HTML:\n\n"
        + html
    )
    if verbose:
        parent_note = f", parent={parent_word}" if parent_word else ""
        print(f"[api] calling OpenAI for back fields: word={traditional or simplified}{parent_note}, model={model or 'default'}")
        print(f"[api] required keys: {', '.join(req)}")
        print(f"[api] optional keys: {', '.join(opt)}")
    _t0 = time.time()
    try:
        data = client.complete_json(system=system, user=user)
    except KeyboardInterrupt:
        # Propagate to top-level clean handler
        raise
    except Exception as e:
        if verbose:
            print(f"[api] OpenAI call failed: {e}")
        data = {}
    _dt_ms = int((time.time() - _t0) * 1000)
    if verbose:
        print(f"[api] OpenAI complete in {_dt_ms} ms")
        try:
            size_kb = len(html.encode('utf-8')) // 1024
        except Exception:
            size_kb = len(html) // 1024
        print(f"[api] HTML bytes (pruned): {size_kb} KB")
    # Build expected JSON structure from schema (defaults)
    def _expected_defaults() -> Dict[str, Dict[str, str] | str | list]:
        out: Dict[str, Dict[str, str] | str | list] = {}
        ctx = {"wiktionary_url": trad_url, "traditional": traditional, "simplified": simplified}
        for f in BACK_SCHEMA.fields:
            key = _field_name_to_key(f.name)
            if f.children:
                # container (e.g., etymology)
                child_obj: Dict[str, str | list] = {}
                for ch in f.children or []:
                    # Include child if it is model-generated OR has a default provider
                    if ch.ai_prompt is None and ch.default_provider is None:
                        continue
                    ck = _field_name_to_key(ch.name)
                    if ch.default_provider is not None:
                        child_obj[ck] = ch.default_provider(ctx)
                    else:
                        child_obj[ck] = [] if ch.field_type == "sublist" else ""
                if child_obj:
                    out[key] = child_obj
            else:
                # leaf
                if f.ai_prompt is None and f.default_provider is None:
                    continue
                if f.default_provider is not None:
                    out[key] = f.default_provider(ctx)
                else:
                    out[key] = [] if f.field_type == "sublist" else ""
        return out

    result: Dict[str, Dict[str, str] | str | list] = _expected_defaults()
    if verbose:
        print("[api] defaults constructed for back fields")

    # Merge model data into expected structure
    if isinstance(data, dict):
        for f in BACK_SCHEMA.fields:
            k = _field_name_to_key(f.name)
            if f.children:
                src = data.get(k)
                if isinstance(src, dict):
                    dst = result.get(k)
                    if isinstance(dst, dict):
                        for ch in f.children or []:
                            if ch.ai_prompt is None:
                                continue
                            ck = _field_name_to_key(ch.name)
                            if ck in src:
                                val = src.get(ck)
                                if ch.field_type == "sublist" and isinstance(val, list):
                                    dst[ck] = [str(_clean_value(str(it))).strip() for it in val if str(it).strip()]
                                elif isinstance(val, str):
                                    dst[ck] = _clean_value(val.strip())
            else:
                # Leaf fields: only merge those that are model-generated
                if f.ai_prompt is not None and k in data:
                    val = data.get(k)
                    if f.field_type == "sublist" and isinstance(val, list):
                        result[k] = [str(_clean_value(str(it))).strip() for it in val if str(it).strip()]
                    elif isinstance(val, str):
                        result[k] = _clean_value(val.strip())
    if verbose:
        print("[api] merge complete; returning back fields")
    # Normalize simplification_rule
    return result  # type: ignore[return-value]



def build_row_map(rows: List[Tuple[str, str, str, str, str]]) -> Dict[str, Dict[str, str]]:
    mapping: Dict[str, Dict[str, str]] = {}
    for simp, trad, pin, eng, _ in rows:
        card = {"english": eng, "traditional": trad or simp, "simplified": simp or trad, "pinyin": pin}
        if simp and simp not in mapping:
            mapping[simp] = card
        if trad and trad not in mapping:
            mapping[trad] = card
    return mapping


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
    md_path = out_dir / f"{word}.md"
    parts: List[str] = []
    parts.append(f"## {english}")
    # If relation indicates sub-word, add subheader
    rel = relation.strip()
    if rel:
        # Normalize legacy relation labels
        rel_norm = rel.replace("subword", "sub-word").replace("subcomponent", "sub-component")
        # Expecting format like: sub-word of "<parent>"
        parts.append(f"### {rel_norm}")
    parts.append("---")

    # Helper to render schema label with placeholders
    def render_label(name: str) -> str:
        label = name.replace("{traditional}", traditional).replace("{simplified}", simplified)
        return label

    # Map schema fields by key for access
    name_by_key: Dict[str, str] = {}
    for f in BACK_SCHEMA.fields:
        k = _field_name_to_key(f.name)
        name_by_key[k] = f.name

    # Print the core required fields using schema labels
    for base_key in ("traditional", "simplified", "pronunciation", "definition"):
        label = render_label(name_by_key.get(base_key, base_key))
        if base_key == "definition":
            value = english
        elif base_key == "traditional":
            value = traditional
        elif base_key == "simplified":
            value = simplified
        else:
            value = pinyin
        parts.append(f"- **{label}:**: {value}")

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
                # If section value is missing from model output, still render its children from defaults
                section_val = value if isinstance(value, dict) else {}
                for ch in field.children or []:
                    ck = _field_name_to_key(ch.name)
                    render_field(ch, section_val.get(ck), indent + 1)
                return
            # For non-section leaves/sublists, require ai_prompt OR a default_provider (schema-driven)
            if field.ai_prompt is None and field.default_provider is None:
                return
            if field.field_type == "sublist":
                items = value if isinstance(value, list) else []
                # Enforce max_items if provided by schema
                try:
                    max_items = getattr(field, "max_items", None)
                except Exception:
                    max_items = None
                if isinstance(max_items, int) and max_items > 0:
                    items = items[:max_items]
                if items:
                    parts.append(f"{pad}- **{label}:**")
                    for item in items:
                        parts.append(f"{pad}  - {str(item)}")
                else:
                    fallback = getattr(field, "empty_fallback", None) or ""
                    if fallback:
                        parts.append(f"{pad}- **{label}:**")
                        parts.append(f"{pad}  - {fallback}")
                return
            # line
            if isinstance(value, str) and value.strip():
                clean = _clean_value(value.strip())
                parts.append(f"{pad}- **{label}:**: {clean}")

        # Render all AI-generated fields at top level (including sections)
        # Render all fields from schema using field types; no special-casing
        for f in BACK_SCHEMA.fields:
            k = _field_name_to_key(f.name)
            v = back_fields.get(k) if isinstance(back_fields, dict) else None
            render_field(f, v, indent=0)
    parts.append("%%%")
    content = "\n".join(parts) + "\n"
    md_path.write_text(content, encoding="utf-8")
    return md_path


def process_folder(folder: Path, model: Optional[str], verbose: bool, debug: bool, delay_s: float) -> Tuple[int, int]:
    # Only support the canonical filename: -input.parsed.csv
    parsed_path = folder / "-input.parsed.csv"
    if not parsed_path.exists():
        if verbose:
            print(f"[skip] No -input.parsed.csv in {folder}")
        return 0, 0
    rows = read_parsed_input(parsed_path)
    if verbose:
        print(f"[info] {folder}: {len(rows)} word(s)")
    log_debug(debug, f"parsed rows sample: {rows[:3]}")
    out_dir = folder
    successes = 0
    comp_cache: Dict[str, object] = {}
    for simp, trad, pin, eng, rel in rows:
        word = simp or trad
        try:
            md_path = out_dir / f"{word}.md"
            if md_path.exists():
                if verbose:
                    print(f"[skip] Card already exists: {md_path.name}")
                continue
            html_path = out_dir / f"{word}.input.html"
            if html_path.exists():
                combined_html = html_path.read_text(encoding="utf-8", errors="ignore")
                if verbose:
                    print(f"[info] Using cached HTML for {word}")
                log_debug(debug, f"cached html bytes for {word}: {len(combined_html)}")
            else:
                # Build combined HTML: simplified/traditional sections (if distinct)
                combined_sections: List[str] = []
                fetched_set: Dict[str, bool] = {}
                # Fetch simplified and traditional forms distinctly (avoid redundant fetches)
                for form in [simp, trad]:
                    form = (form or "").strip()
                    if not form or form in fetched_set:
                        continue
                    fetched_set[form] = True
                    form_html, form_status = fetch_wiktionary_html_status(form)
                    if verbose:
                        print(f"[info] Wiktionary GET {form} -> {form_status}")
                    if form_status == 200 and form_html:
                        combined_sections.append(section_header(form) + sanitize_html(form_html))
                        log_debug(debug, f"fetched html bytes for {form}: {len(form_html)}")
                    else:
                        combined_sections.append(section_header(form))
                    if delay_s > 0:
                        time.sleep(delay_s)
                combined_html = "\n\n".join(combined_sections)
                # Always write a .input.html, even if empty sections
                html_path.write_text(combined_html, encoding="utf-8")
                if verbose:
                    print(f"[ok] Wrote {html_path.name} ({len(combined_html)} bytes)")
                log_debug(debug, f"combined html size for {word}: {len(combined_html)}")
            # Build single card markdown, enriching with AI-derived back fields
            if verbose:
                print(
                    f"[info] OpenAI back-fields for {word} (model={model or 'default'}), HTML bytes={len(combined_html)}"
                )
            log_debug(debug, f"calling extract_back_fields_from_html for {word}; pinyin='{pin}'")
            back = extract_back_fields_from_html(
                simplified=word,
                traditional=trad or word,
                english=eng,
                html=combined_html,
                model=model,
                verbose=verbose,
                parent_word=None,
            )
            if verbose:
                et = back.get("etymology") if isinstance(back, dict) else None
                et_type = et.get("type") if isinstance(et, dict) else ""
                et_sr = et.get("simplification_rule") if isinstance(et, dict) else ""
                sr_flag = "present" if (simp and trad and simp != trad and et_sr) else "skipped"
                print(f"[ok] Back fields extracted: etymology.type='{et_type}', simplification={sr_flag}")
            log_debug(debug, f"back keys for {word}: {list(back.keys()) if isinstance(back, dict) else type(back)}")
            write_simple_card_md(
                out_dir,
                word,
                eng,
                trad or word,
                simp or word,
                pin,
                rel,
                back_fields=back,
            )
            log_debug(debug, f"wrote md for {word}: pinyin='{pin}', relation='{rel}'")
            # If this is a single-character headword, generate full sub-component subtree based on etymology
            try:
                if isinstance(back, dict) and isinstance(word, str) and len(word) == 1:
                    comp_list = _collect_components_from_back(back)
                    log_debug(debug, f"components for {word}: {comp_list}")
                    if comp_list:
                        desc = (
                            back.get("etymology", {}).get("description")
                            if isinstance(back.get("etymology"), dict)
                            else ""
                        )
                        english_map = _parse_component_english_map(str(desc))
                        visited: set = set([word])
                        for ch in comp_list:
                            log_debug(debug, f"recurse into {word}.{ch} english='{english_map.get(ch, '')}'")
                            _generate_component_subtree(
                                out_dir=out_dir,
                                prefix=word,
                                ch=ch,
                                component_english=english_map.get(ch, ""),
                                parent_english=eng,
                                model=model,
                                verbose=verbose,
                                debug=debug,
                                delay_s=delay_s,
                                visited=visited,
                                depth=1,
                                comp_cache=comp_cache,
                            )
            except Exception as e:
                if verbose:
                    print(f"[warn] sub-component generation failed for {word}: {e}")
                # Always fail hard on sub-component generation errors
                raise
            successes += 1
            if verbose:
                print(f"[ok] Card for {word}")
        except KeyboardInterrupt:
            if verbose:
                print("[info] Interrupted by user; stopping folder processing")
            return len(rows), successes
        except Exception as e:
            if verbose:
                print(f"[error] {word}: {e}")
        if delay_s > 0:
            time.sleep(delay_s)
    return len(rows), successes


def find_parsed_folders(root: Path) -> List[Path]:
    # Only support the canonical filename: -input.parsed.csv
    folders: List[Path] = []
    seen = set()
    for path in root.rglob("-input.parsed.csv"):
        parent = Path(path).parent
        if parent not in seen:
            folders.append(parent)
            seen.add(parent)
    folders.sort()
    return folders


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate flashcard .md files from parsed vocab (one-to-one) and fetch combined HTML")
    parser.add_argument(
        "--root",
        default=str(Path(__file__).parent / "output"),
        help="Root directory to scan (default: ./output)",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("OPENAI_MODEL"),
        help="OpenAI model name (overrides OPENAI_MODEL)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.0,
        help="Optional delay in seconds between requests to Wiktionary",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable extremely verbose debugging logs",
    )
    args = parser.parse_args(argv)

    root = Path(args.root)
    if not root.exists():
        print(f"[error] Root directory does not exist: {root}", file=sys.stderr)
        return 2

    try:
        folders = find_parsed_folders(root)
        if args.verbose or args.debug:
            print(f"[info] Found {len(folders)} folder(s) with -input.parsed.csv under {root}")
        total_words = 0
        total_cards = 0
        for folder in folders:
            words, cards = process_folder(folder, args.model, args.verbose, args.debug, args.delay)
            total_words += words
            total_cards += cards

        if args.verbose or args.debug:
            print(f"[done] Processed {total_words} word(s), created {total_cards} card(s)")
        return 0
    except KeyboardInterrupt:
        print("[info] Interrupted by user (Ctrl-C). Exiting cleanly.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())


