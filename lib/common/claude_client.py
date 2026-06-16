"""Claude (Anthropic) LLM client — a drop-in alternative to OpenAIClient.

Same interface as ``lib.common.openai.OpenAIClient`` (``complete_json`` /
``complete_structured``) so the generator can switch providers via
``get_llm_client`` (FLASHCARD_LLM=claude).

Auth + rotation
---------------
The Anthropic Pro/Max **subscription** is reached with OAuth tokens
(``sk-ant-oat-…`` from ``claude setup-token``) rather than a metered API key.
A subscription is sized for one human, so a bulk run can trip its rate/usage
limit. Mirroring the sonoma scan-framework, we keep a POOL of OAuth tokens and
rotate to the next one when a call fails with a class a *different* token could
fix — ``auth`` / ``rate_limit`` / ``quota`` (other failures don't rotate). A
rate/quota-limited token is parked on a cooldown so we don't keep hitting it.

Transports (auto-selected):
- **CLI** (default): shells out to the authenticated ``claude`` CLI with
  ``CLAUDE_CODE_OAUTH_TOKEN`` set to the active token. Works with the
  subscription with no API key. This is what runs in this environment.
- **SDK**: if ``ANTHROPIC_API_KEY`` is set, uses the ``anthropic`` SDK directly.

Token sources (first non-empty wins), each a list:
- ``CLAUDE_OAUTH_TOKENS`` — comma/whitespace separated
- ``CLAUDE_OAUTH_TOKEN_1``, ``CLAUDE_OAUTH_TOKEN_2``, … (and ``_BACKUP``)
- ``~/.config/flashcards/claude_oauth_tokens`` — one token per line
- none configured → a single slot using the CLI's logged-in session
"""
import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from tenacity import retry, stop_after_attempt, wait_exponential

_ROTATE_COOLDOWN_S = 15 * 60  # park a rate/quota-limited token this long


def _load_tokens() -> List[Optional[str]]:
    raw = os.environ.get("CLAUDE_OAUTH_TOKENS", "")
    toks = [t for t in re.split(r"[,\s]+", raw) if t]
    if not toks:
        numbered = []
        for k in sorted(os.environ):
            if re.fullmatch(r"CLAUDE_OAUTH_TOKEN(_\d+|_BACKUP)?", k) and os.environ[k].strip():
                numbered.append(os.environ[k].strip())
        toks = numbered
    if not toks:
        f = Path.home() / ".config" / "flashcards" / "claude_oauth_tokens"
        if f.exists():
            toks = [ln.strip() for ln in f.read_text().splitlines()
                    if ln.strip() and not ln.startswith("#")]
    # No explicit tokens -> one slot using the CLI's existing login session.
    return toks or [None]


def _classify(text: str) -> str:
    """Coarse failure class (mirrors sonoma's claude-reviewer-run classifier)."""
    t = (text or "").lower()
    if re.search(r"oauth|unauthorized|authentication|forbidden|permission|invalid api|401|403", t):
        return "auth"
    if re.search(r"rate.?limit|429|too many requests|overloaded|529", t):
        return "rate_limit"
    if re.search(r"quota|usage limit|usage_limit|credit|exceeded|insufficient", t):
        return "quota"
    return "other"


_ROTATABLE = {"auth", "rate_limit", "quota"}


class _RotateError(Exception):
    def __init__(self, cls): self.cls = cls


class ClaudeClient:
    def __init__(self, model: Optional[str] = None) -> None:
        # Ignore OpenAI-style model ids (e.g. "gpt-4o"); use a Claude model/alias.
        m = model if (model and str(model).startswith("claude")) else None
        self.model = m or os.environ.get("CLAUDE_MODEL") or "sonnet"
        self.tokens = _load_tokens()
        self._idx = 0
        self._cooldown: Dict[int, float] = {}  # token index -> epoch when usable again
        self._api_key = os.environ.get("ANTHROPIC_API_KEY")
        self._sdk = None
        if self._api_key:
            try:
                from anthropic import Anthropic
                self._sdk = Anthropic(api_key=self._api_key)
            except Exception:
                self._sdk = None

    # ---- token pool -------------------------------------------------------
    def _next_usable(self) -> int:
        n = len(self.tokens)
        now = time.time()
        for off in range(n):
            i = (self._idx + off) % n
            if self._cooldown.get(i, 0) <= now:
                self._idx = i
                return i
        # all cooling down -> use the one with the soonest expiry
        i = min(range(n), key=lambda j: self._cooldown.get(j, 0))
        self._idx = i
        return i

    def _park(self, i: int):
        self._cooldown[i] = time.time() + _ROTATE_COOLDOWN_S

    # ---- transports -------------------------------------------------------
    def _call_sdk(self, system: str, user: str, token: Optional[str]) -> str:
        client = self._sdk
        if token:  # OAuth bearer instead of api key
            from anthropic import Anthropic
            client = Anthropic(auth_token=token,
                               default_headers={"anthropic-beta": "oauth-2025-04-20"})
        msg = client.messages.create(
            model=self.model if self.model.startswith("claude") else "claude-sonnet-4-6",
            max_tokens=4096, system=system,
            messages=[{"role": "user", "content": user}])
        return "".join(getattr(b, "text", "") for b in msg.content if getattr(b, "type", "") == "text")

    def _call_cli(self, system: str, user: str, token: Optional[str]) -> str:
        prompt = (f"{system}\n\n{user}\n\n"
                  "Respond with ONLY one valid JSON object — no prose, no markdown fences.")
        env = dict(os.environ)
        if token:
            env["CLAUDE_CODE_OAUTH_TOKEN"] = token
        proc = subprocess.run(
            ["claude", "-p", prompt, "--output-format", "json", "--model", self.model],
            capture_output=True, text=True, env=env, timeout=240)
        if proc.returncode != 0:
            raise _RotateError(_classify(proc.stderr or proc.stdout))
        data = json.loads(proc.stdout)
        if data.get("is_error"):
            raise _RotateError(_classify(json.dumps(data)))
        return data.get("result", "") or ""

    # ---- json parsing -----------------------------------------------------
    @staticmethod
    def _parse_json(text: str) -> Any:
        t = (text or "").strip()
        t = re.sub(r"^```(?:json)?\s*", "", t)
        t = re.sub(r"\s*```$", "", t).strip()
        try:
            return json.loads(t)
        except Exception:
            m = re.search(r"\{.*\}|\[.*\]", t, re.S)
            if not m:
                raise
            return json.loads(m.group(0))

    # ---- public API (matches OpenAIClient) --------------------------------
    @retry(reraise=True, stop=stop_after_attempt(4), wait=wait_exponential(multiplier=1, min=1, max=8))
    def complete_json(self, system: str, user: str, schema_hint: Optional[str] = None,
                      verbose: bool = False) -> Any:
        last = None
        for _ in range(len(self.tokens) * 2):
            i = self._next_usable()
            token = self.tokens[i]
            try:
                text = (self._call_sdk(system, user, token) if (self._sdk or token and self._api_key)
                        else self._call_cli(system, user, token))
                return self._parse_json(text)
            except _RotateError as e:
                last = e
                label = "session" if token is None else f"token[{i}]"
                if e.cls in _ROTATABLE:
                    print(f"[claude] {label} hit {e.cls}; rotating to next OAuth token")
                    self._park(i)
                    self._idx = (i + 1) % len(self.tokens)
                    continue
                raise RuntimeError(f"Claude call failed ({e.cls})")
            except Exception as e:
                # Non-classified transport error: try rotating once, else bubble up.
                last = e
                self._idx = (i + 1) % len(self.tokens)
        raise RuntimeError(f"Claude call failed after exhausting {len(self.tokens)} token(s): {last}")

    def complete_structured(self, system: str, user: str, schema: Dict[str, Any]) -> Any:
        inner = schema.get("schema", schema) if isinstance(schema, dict) else schema
        if self._sdk and not any(self.tokens):
            tool = {"name": "emit_result", "description": "Return the structured result",
                    "input_schema": inner}
            msg = self._sdk.messages.create(
                model=self.model if self.model.startswith("claude") else "claude-sonnet-4-6",
                max_tokens=2048, system=system, messages=[{"role": "user", "content": user}],
                tools=[tool], tool_choice={"type": "tool", "name": "emit_result"})
            for b in msg.content:
                if getattr(b, "type", "") == "tool_use":
                    return b.input
            return {}
        return self.complete_json(system, user + f"\n\nReturn JSON matching this schema:\n{json.dumps(inner)}")
