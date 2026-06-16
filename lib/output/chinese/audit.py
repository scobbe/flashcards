"""Post-generation card audit.

Scans rendered ``N.<word>.md`` cards for compliance and quality problems and
returns a list of issues. Two tiers:

- **Deterministic** checks (fast, no API) — run automatically after generation:
  role-word definitions, empty definition/pinyin/interpretation, Old-Chinese
  reconstructions, vacuous-interpretation heuristics, role-word component
  glosses, and per-batch card-count vs parsed-input mismatch.
- **LLM** check (opt-in, ``llm=True``) — judges each interpretation for genuine
  vacuousness, tuned so honest phono-semantic explanations ("semantic radical +
  phonetic for sound") are NOT flagged (forcing a "mechanism" there invites
  fabrication).

Used by ``generate.py`` (deterministic, prints flags) and ``scripts/audit_cards.py``.
"""
import re
from pathlib import Path
from typing import List, NamedTuple, Optional

from lib.common import is_cjk_char
from lib.output.chinese.cards import _is_role_word

# HIGH-PRECISION heuristic for clearly-circular interpretations (few false
# positives). It only catches restatement templates with no mechanism; subtler
# vacuousness is left to the --llm judge (the regex cannot tell an honest
# phono-semantic note from an empty one). Tuned against the corpus.
_VACUOUS_RX = re.compile("|".join([
    r"this combination resulted in",
    r"hence its meanings?\b",
    r"combin(?:es|ing|ed) .{0,80}? to (?:express|convey|represent|produce) the (?:idea|concept|notion|meaning|sense)",
    r"come together to (?:express|convey|form|represent|create)",
    r"the two (?:parts|components) together (?:suggest|represent|express|convey|symbolize)",
    r"express(?:es|ing)? the (?:idea|concept|notion) of .{0,60}? hence",
]), re.IGNORECASE)
_OC_RX = re.compile(r"\(OC\b|\bOC\s*\*")
# A traditional annotation should wrap exactly ONE differing character — `字(繁)`
# or an empty `( )` slot. A paren holding 2+ CJK chars or sentence punctuation is
# an un-expanded clause-level annotation (a formatting bug).
_PAREN_RX = re.compile(r"\(([^)]*)\)")
_CJK_PUNCT = "，。！？；：、…—·「」『』《》〈〉"


def _cjk_count(s: str) -> int:
    return sum(1 for c in s if "一" <= c <= "鿿" or "㐀" <= c <= "䶿"
               or "豈" <= c <= "﫿" or "\U00020000" <= c <= "\U0002ebef")
_FIELD_RX = re.compile(r"^(\s*)- \*\*(definition|pinyin|interpretation|type|description|simplification):\*\* (.*)$")
_HEADING_RX = re.compile(r"^(##+) (.+)$")
# A top-level field bullet (no indent): `- **components:**`, `- **etymology:**`, …
_TOP_FIELD_RX = re.compile(r"^- \*\*(\w+):\*\*")
# A component-list gloss line: "    - <gloss>" (3rd-level bullet under components).
_GLOSS_RX = re.compile(r"^\s{4,}- (.+)$")


class Issue(NamedTuple):
    severity: str   # "error" | "warn"
    kind: str
    location: str   # file:heading
    detail: str


class Card(NamedTuple):
    heading: str
    is_sub: bool
    fields: dict


def parse_cards(md_path: Path) -> List[Card]:
    """Parse a rendered card file into per-section field dicts."""
    cards: List[Card] = []
    cur = None
    front_divider_seen = False
    for line in md_path.read_text(encoding="utf-8").splitlines():
        h = _HEADING_RX.match(line)
        # A new card section begins at a `## 词(繁)` or `### breadcrumb` heading that
        # is a Chinese headword (contains a CJK char), not the english/pinyin lines.
        if h and any("一" <= c <= "鿿" or "㐀" <= c <= "䶿" for c in h.group(2)):
            level = len(h.group(1))
            # the `## {english}` and `### {pinyin}` front lines have no CJK, so excluded.
            # Drop field-less sections (the reverse-card footer `---\n## headword`).
            if cur is not None and cur.fields:
                cards.append(cur)
            cur = Card(heading=h.group(2).strip(), is_sub=(level >= 3), fields={})
            continue
        f = _FIELD_RX.match(line)
        if f and cur is not None:
            name, val = f.group(2), f.group(3).strip()
            # keep first occurrence per card (definition appears once)
            cur.fields.setdefault(name, val)
    if cur is not None and cur.fields:
        cards.append(cur)
    return cards


def audit_card_file(md_path: Path, rel: str) -> List[Issue]:
    issues: List[Issue] = []
    text = md_path.read_text(encoding="utf-8")

    # whole-file: Old Chinese reconstructions must never appear
    for m in _OC_RX.finditer(text):
        ctx = text[max(0, m.start() - 20):m.start() + 20].replace("\n", " ")
        issues.append(Issue("error", "old-chinese", rel, f"OC reconstruction: …{ctx}…"))
        break

    # whole-file: clause-level traditional annotations (mis-formatted parens). A
    # genuine `simp(trad)` annotation has a PARALLEL simplified run immediately
    # before it: same length, differing only at CJK positions. That distinguishes
    # a real un-expanded annotation from a legitimate Chinese prose parenthetical
    # ("…(古時候…)") or an English gloss ("(foot)"), which aren't parallel.
    for m in _PAREN_RX.finditer(text):
        content = m.group(1)
        # A single differing char `字(繁)` is the CORRECT per-character format;
        # only a multi-char `(…)` that parallels the preceding run is malformed.
        if len(content) < 2 or _cjk_count(content) < 1:
            continue
        before = text[m.start() - len(content):m.start()]
        if len(before) != len(content):
            continue
        diffs = 0
        ok = True
        for a, b in zip(before, content):
            if a == b:
                continue
            if is_cjk_char(a) and is_cjk_char(b):
                diffs += 1
            else:
                ok = False
                break
        if ok and diffs:
            issues.append(Issue("error", "malformed-parens", rel,
                                f"clause-level annotation: ({content[:36]})"))

    # role-word component glosses — ONLY within a `- **components:**` section
    # (component bullets aren't cleaned at render). Track section so description
    # formula lines ("semantic A + phonetic B ->") aren't mistaken for glosses.
    in_components = False
    for line in text.splitlines():
        top = _TOP_FIELD_RX.match(line)
        if top:
            in_components = (top.group(1) == "components")
            continue
        if in_components:
            g = _GLOSS_RX.match(line)
            if g and _is_role_word(g.group(1)):
                issues.append(Issue("warn", "role-word-component", rel, f"component gloss: {g.group(1)!r}"))

    for card in parse_cards(md_path):
        loc = f"{rel}::{card.heading}"
        defn = card.fields.get("definition", "")
        if not defn:
            issues.append(Issue("error", "empty-definition", loc, "no definition"))
        elif _is_role_word(defn):
            issues.append(Issue("error", "role-word-definition", loc, f"definition is a role word: {defn!r}"))
        if not card.fields.get("pinyin"):
            issues.append(Issue("warn", "missing-pinyin", loc, "no pinyin"))
        interp = card.fields.get("interpretation", "")
        # Interpretation is the key explanation for a SINGLE character; for a
        # multi-char compound the `description` (A + B = …) already carries it,
        # so only flag a single-char card that has an etymology but no interpretation.
        headword = card.heading.split("→")[-1]
        n_cjk = sum(1 for c in headword if "一" <= c <= "鿿" or "㐀" <= c <= "䶿")
        if n_cjk == 1 and card.fields.get("type") and not interp:
            issues.append(Issue("warn", "empty-interpretation", loc, "single-char etymology with no interpretation"))
        if interp and _VACUOUS_RX.search(interp):
            issues.append(Issue("warn", "vacuous-interpretation?", loc, interp[:120]))
    return issues


def _card_files(output_dir: Path) -> List[Path]:
    return [p for p in sorted(output_dir.glob("*.md")) if not p.name.startswith("-")]


def audit_output_dir(output_dir: Path, repo_root: Optional[Path] = None,
                     llm: bool = False, model: Optional[str] = None) -> List[Issue]:
    """Audit every card in one batch ``output/`` dir. Returns a list of Issues."""
    output_dir = Path(output_dir)
    issues: List[Issue] = []
    files = _card_files(output_dir)
    rootp = repo_root or Path.cwd()
    for p in files:
        try:
            rel = str(p.relative_to(rootp))
        except ValueError:
            rel = str(p)
        issues += audit_card_file(p, rel)

    # batch-level: headword card count vs parsed-input rows
    parsed = output_dir.parent / "input-parsed" / "-input.parsed.csv"
    if parsed.exists():
        n_rows = sum(1 for ln in parsed.read_text(encoding="utf-8").splitlines() if ln.strip())
        if n_rows and len(files) < n_rows:
            issues.append(Issue("error", "card-count-mismatch", str(output_dir),
                                f"{len(files)} cards < {n_rows} parsed input rows (possible dropped cards)"))

    if llm:
        issues += _llm_audit(files, rootp, model)
    return issues


def _llm_audit(files, rootp, model) -> List[Issue]:
    """LLM-judge interpretations for genuine vacuousness (honest phonetic = OK)."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from lib.common.openai import get_llm_client
    client = get_llm_client(model=model)
    SYS = (
        "You grade ONE Chinese character/word etymology interpretation from a flashcard as "
        "GOOD or VACUOUS. DEFAULT TO GOOD — only answer VACUOUS when the text genuinely "
        "explains nothing. An interpretation is GOOD if it has ANY of: a concrete mental image, "
        "a causal/semantic chain, a pictogram description ('depicts X'), a historical/loan note, "
        "or an honest phono-semantic note (a semantic part sets the domain and another part is "
        "stated to supply only the SOUND — this is correct and GOOD, not vacuous). "
        "It is VACUOUS only if it is purely circular — it restates that the parts 'combine to "
        "express/convey/represent' the meaning with NO image, NO chain, NO honest sound note — "
        "OR it fabricates a semantic story from a part that is purely phonetic.\n"
        "GOOD examples:\n"
        "- 人: 'depicts the essential form of a human' (pictogram).\n"
        "- 付: '亻 person + a hand -> the action of handing something over' (image+chain).\n"
        "- 緊: 'semantic 糸 silk-thread + phonetic 臤 for sound; threads pulled taut are tight' (honest phonetic + image).\n"
        "- 是: 'the noonday sun is the standard of straightness 正 -> correct -> what is so -> yes/to be' (chain).\n"
        "VACUOUS examples:\n"
        "- 'combines the sun 日 with 正 (phonetic); this combination expresses the idea of correctness, hence its meanings.' (pure restatement)\n"
        "- 'the two parts together convey the concept of X.' (no mechanism)\n"
        "Reply JSON {\"v\":\"GOOD\"|\"VACUOUS\"}.")
    targets = []
    for p in files:
        try:
            rel = str(p.relative_to(rootp))
        except ValueError:
            rel = str(p)
        for card in parse_cards(p):
            it = card.fields.get("interpretation", "")
            if it:
                targets.append((rel, card.heading, it))

    def judge(t):
        rel, head, it = t
        try:
            r = client.complete_json(system=SYS, user=f"{head}:\n{it}")
            return (rel, head, it, str(r.get("v", "")).upper())
        except Exception:
            return (rel, head, it, "ERR")

    out: List[Issue] = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        for f in as_completed([ex.submit(judge, t) for t in targets]):
            rel, head, it, v = f.result()
            if v == "VACUOUS":
                out.append(Issue("warn", "vacuous-interpretation(llm)", f"{rel}::{head}", it[:120]))
    return out


def format_report(issues: List[Issue]) -> str:
    if not issues:
        return "✓ audit: no issues"
    errs = [i for i in issues if i.severity == "error"]
    warns = [i for i in issues if i.severity == "warn"]
    lines = [f"audit: {len(errs)} error(s), {len(warns)} warning(s)"]
    by_kind = {}
    for i in issues:
        by_kind.setdefault((i.severity, i.kind), []).append(i)
    for (sev, kind), items in sorted(by_kind.items()):
        lines.append(f"  [{sev}] {kind}: {len(items)}")
        for it in items[:8]:
            lines.append(f"      {it.location} — {it.detail}")
        if len(items) > 8:
            lines.append(f"      … +{len(items) - 8} more")
    return "\n".join(lines)
