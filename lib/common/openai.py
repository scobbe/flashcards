import json
import os
from typing import Any, Dict, Optional

from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

try:
    from openai import OpenAI, BadRequestError
except Exception:  # pragma: no cover
    OpenAI = None  # type: ignore
    BadRequestError = Exception  # type: ignore


class OpenAIClient:
    def __init__(self, model: Optional[str] = None) -> None:
        self.model = model or os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not set in environment")
        if OpenAI is None:
            raise RuntimeError("openai package is not available")
        self.client = OpenAI(api_key=api_key, timeout=60.0)

    @retry(reraise=True, stop=stop_after_attempt(4), wait=wait_exponential(multiplier=1, min=1, max=8))
    def complete_json(self, system: str, user: str, schema_hint: Optional[str] = None) -> Any:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0,
                response_format={"type": "json_object"},
            )
        except BadRequestError as e:  # type: ignore
            # Retry without temperature for models that don't allow changing it
            msg = str(getattr(e, "message", ""))
            if "temperature" in msg or "unsupported" in msg:
                resp = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    response_format={"type": "json_object"},
                )
            else:
                raise
        text = resp.choices[0].message.content or "{}"
        try:
            data = json.loads(text)
        except Exception:
            # Some models may wrap arrays in code fences; try to strip
            stripped = text.strip().strip("`")
            data = json.loads(stripped)
        return data


