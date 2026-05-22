from __future__ import annotations

import json
import os
import re
from typing import Callable, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


class DeepSeekClient:
    def __init__(self) -> None:
        self.api_key = os.getenv("DEEPSEEK_API_KEY")
        self.model = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
        self.base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def complete_json(self, system: str, user: str, schema: type[T]) -> T:
        parsed, _ = self.complete_json_with_raw(system, user, schema)
        return parsed

    def complete_json_with_raw(self, system: str, user: str, schema: type[T], on_chunk: Callable[[str], None] | None = None) -> tuple[T, str]:
        if not self.api_key:
            raise RuntimeError("DEEPSEEK_API_KEY is not set")

        content = self._complete_stream(system, user, on_chunk) if on_chunk else self._complete(system, user)
        try:
            return schema.model_validate_json(extract_json(content)), content
        except (ValidationError, json.JSONDecodeError) as exc:
            repair_prompt = (
                "Repair the following response so it is valid JSON matching the requested schema. "
                "Return JSON only, with no markdown.\n\n"
                f"Validation error: {exc}\n\nResponse:\n{content}"
            )
            if on_chunk:
                on_chunk("\n\n[repair]\n")
            repaired = self._complete_stream(system, repair_prompt, on_chunk) if on_chunk else self._complete(system, repair_prompt)
            return schema.model_validate_json(extract_json(repaired)), repaired

    def _complete(self, system: str, user: str) -> str:
        response = httpx.post(
            f"{self.base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json={
                "model": self.model,
                "temperature": 0.15,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
            timeout=60,
        )
        response.raise_for_status()
        payload = response.json()
        return payload["choices"][0]["message"]["content"]

    def _complete_stream(self, system: str, user: str, on_chunk: Callable[[str], None]) -> str:
        chunks: list[str] = []
        with httpx.stream(
            "POST",
            f"{self.base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json={
                "model": self.model,
                "temperature": 0.15,
                "response_format": {"type": "json_object"},
                "stream": True,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
            timeout=httpx.Timeout(60, read=120),
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line.startswith("data:"):
                    continue
                data = line.removeprefix("data:").strip()
                if data == "[DONE]":
                    break
                payload = json.loads(data)
                delta = payload["choices"][0].get("delta", {}).get("content") or ""
                if not delta:
                    continue
                chunks.append(delta)
                on_chunk(delta)
        return "".join(chunks)


def extract_json(content: str) -> str:
    clean = content.strip()
    if clean.startswith("```"):
        clean = re.sub(r"^```(?:json)?", "", clean).strip()
        clean = re.sub(r"```$", "", clean).strip()
    first_obj = clean.find("{")
    last_obj = clean.rfind("}")
    if first_obj >= 0 and last_obj > first_obj:
        return clean[first_obj : last_obj + 1]
    return clean
