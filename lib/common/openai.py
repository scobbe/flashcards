"""OpenAI client for API calls."""

import json
import os
import time
from typing import Any, Dict, Optional

from tenacity import retry, stop_after_attempt, wait_exponential

try:
    from openai import OpenAI
except Exception:  # pragma: no cover
    OpenAI = None  # type: ignore


class OpenAIClient:
    def __init__(self, model: Optional[str] = None) -> None:
        self.model = model or "gpt-4o"
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not set in environment")
        if OpenAI is None:
            raise RuntimeError("openai package is not available")
        self.client = OpenAI(api_key=api_key, timeout=120.0)

    @retry(reraise=True, stop=stop_after_attempt(4), wait=wait_exponential(multiplier=1, min=1, max=8))
    def complete_structured(self, system: str, user: str, schema: Dict[str, Any]) -> Any:
        """Complete with structured outputs (JSON schema enforcement)."""
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_completion_tokens=2048,
            response_format={"type": "json_schema", "json_schema": schema},
        )
        text = resp.choices[0].message.content or "{}"
        return json.loads(text)

    def _complete_json_once(self, messages: list, verbose: bool = False) -> tuple:
        """Single attempt at JSON completion. Returns (data, is_empty, finish_reason)."""
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_completion_tokens=2048,
            response_format={"type": "json_object"},
        )
        text = resp.choices[0].message.content or "{}"
        finish_reason = resp.choices[0].finish_reason

        try:
            data = json.loads(text)
        except Exception:
            stripped = text.strip().strip("`")
            data = json.loads(stripped)

        is_empty = (data == {} or not data)
        return data, is_empty, finish_reason

    @retry(reraise=True, stop=stop_after_attempt(4), wait=wait_exponential(multiplier=1, min=1, max=8))
    def complete_json(self, system: str, user: str, schema_hint: Optional[str] = None, verbose: bool = False) -> Any:
        """Complete with basic JSON mode. Retries once on empty response."""
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

        start = time.time()
        data, is_empty, finish_reason = self._complete_json_once(messages, verbose)
        elapsed = time.time() - start

        if verbose:
            print(f"[openai] [api] {elapsed:.1f}s (model={self.model})")

        if is_empty:
            print(f"[openai] [warning] Empty response (finish_reason: {finish_reason}), retrying...")
            data, is_empty, finish_reason = self._complete_json_once(messages, verbose)
            if is_empty:
                print(f"[openai] [ERROR] Still empty after retry (finish_reason: {finish_reason})")
            else:
                print(f"[openai] [ok] Retry succeeded")

        return data
