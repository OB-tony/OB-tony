from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any
from urllib import request


@dataclass(frozen=True)
class Intent:
    action: str
    model: str | None = None
    domain: list[Any] | None = None
    fields: list[str] | None = None
    values: dict[str, Any] | None = None
    record_id: int | None = None
    confirmation_required: bool = False
    arguments: dict[str, Any] | None = None


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("{") and text.endswith("}"):
        return json.loads(text)
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise ValueError("No JSON object found")
    return json.loads(match.group(0))


class OpenRouterIntentParser:
    def __init__(self, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model

    def parse(self, user_text: str) -> Intent:
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Convert the user request into strict JSON with keys: action, model, domain, fields, values, record_id, "
                        "confirmation_required, arguments. Allowed actions are list, read, create, update, delete, run_reminder, help. "
                        "Only use HR models or linked models. If the user asks about expiring contracts or reminders, return run_reminder. "
                        "Return JSON only."
                    ),
                },
                {"role": "user", "content": user_text},
            ],
            "temperature": 0,
        }
        req = request.Request(
            "https://openrouter.ai/api/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": os.getenv("OPENROUTER_HTTP_REFERER", "http://localhost"),
                "X-Title": os.getenv("OPENROUTER_APP_TITLE", "Odoo HR Agent"),
            },
            method="POST",
        )
        with request.urlopen(req, timeout=60) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
        content = raw["choices"][0]["message"]["content"]
        data = _extract_json(content)
        return Intent(
            action=str(data.get("action", "help")),
            model=data.get("model"),
            domain=data.get("domain"),
            fields=data.get("fields"),
            values=data.get("values"),
            record_id=data.get("record_id"),
            confirmation_required=bool(data.get("confirmation_required", False)),
            arguments=data.get("arguments"),
        )


def fallback_intent(user_text: str) -> Intent:
    text = user_text.lower()
    if "remind" in text or "contract" in text and "expire" in text:
        return Intent(action="run_reminder")
    if any(word in text for word in ("delete", "remove", "destroy")):
        return Intent(action="delete", confirmation_required=True)
    if any(word in text for word in ("update", "change", "edit", "set")):
        return Intent(action="update", confirmation_required=True)
    if any(word in text for word in ("create", "add", "new")):
        return Intent(action="create", confirmation_required=True)
    if any(word in text for word in ("list", "show", "find", "search", "get")):
        return Intent(action="list")
    return Intent(action="help")

