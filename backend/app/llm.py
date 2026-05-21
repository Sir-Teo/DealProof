from __future__ import annotations

import json
import os
import re
from typing import TypeVar

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
        if not self.api_key:
            raise RuntimeError("DEEPSEEK_API_KEY is not set")

        content = self._complete(system, user)
        try:
            return schema.model_validate_json(extract_json(content))
        except (ValidationError, json.JSONDecodeError) as exc:
            repair_prompt = (
                "Repair the following response so it is valid JSON matching the requested schema. "
                "Return JSON only, with no markdown.\n\n"
                f"Validation error: {exc}\n\nResponse:\n{content}"
            )
            repaired = self._complete(system, repair_prompt)
            return schema.model_validate_json(extract_json(repaired))

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
