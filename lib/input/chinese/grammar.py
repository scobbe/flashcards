"""Grammar extraction via OpenAI."""

import csv
import json as _json
from pathlib import Path
from typing import Dict, List

from lib.common import OpenAIClient


def call_openai_for_grammar(text: str, model: str | None) -> List[Dict[str, object]]:
    """Extract grammar rules from free-form notes.
    
    Output: list of {description: str, usage_cn: str, examples: [str, ...]}
    """
    client = OpenAIClient(model=model)
    system = (
        "You extract concise Chinese grammar rules from study notes. "
        "Return ONLY JSON: {\"rules\":[{\"description\":string,\"usage_cn\":string,\"examples\":[string,...]}]} . "
        "Examples should be short, max 5 items total across each rule. "
        "Do NOT censor or filter profanity/vulgarity - include exact translations."
    )
    user = "Extract grammar rules from:\n\n" + text
    data = client.complete_json(system=system, user=user)
    rules = data.get("rules") if isinstance(data, dict) else None
    if not isinstance(rules, list):
        return []
    out: List[Dict[str, object]] = []
    for r in rules:
        if not isinstance(r, dict):
            continue
        desc = str(r.get("description", "")).strip()
        usage = str(r.get("usage_cn", "")).strip()
        ex_raw = r.get("examples", [])
        examples: List[str] = []
        if isinstance(ex_raw, list):
            for it in ex_raw:
                s = str(it).strip()
                if s:
                    examples.append(s)
        if desc:
            out.append({"description": desc, "usage_cn": usage, "examples": examples})
    return out


def write_parsed_grammar_csv(
    raw_path: Path, rules: List[Dict[str, object]], verbose: bool = False
) -> Path:
    """Write parsed grammar rules to CSV."""
    out_path = raw_path.with_name("-input.parsed.grammar.csv")
    # Compute relative path from project root
    project_root = Path(__file__).parent.parent.parent.resolve()
    try:
        folder = str(raw_path.parent.relative_to(project_root))
    except ValueError:
        folder = raw_path.parent.name
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        for r in rules:
            desc = str(r.get("description", ""))
            usage = str(r.get("usage_cn", ""))
            ex = r.get("examples", [])
            ex_json = _json.dumps(ex, ensure_ascii=False) if isinstance(ex, list) else "[]"
            w.writerow([desc, usage, ex_json])
    if verbose:
        print(f"[./{folder}] [file] 💾 Created {out_path.name} ({len(rules)} rules)")
    return out_path

