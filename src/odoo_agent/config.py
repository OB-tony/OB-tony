from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass


def _env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name, default)
    if value is None:
        return None
    value = value.strip()
    return value or None


def infer_supabase_url(service_role_key: str) -> str:
    parts = service_role_key.split(".")
    if len(parts) < 2:
        raise ValueError("Supabase service role key is not a JWT")
    payload = parts[1]
    padding = "=" * (-len(payload) % 4)
    decoded = base64.urlsafe_b64decode(payload + padding).decode("utf-8")
    data = json.loads(decoded)
    ref = data.get("ref")
    if not ref:
        raise ValueError("Could not infer Supabase project ref from service role key")
    return f"https://{ref}.supabase.co"


@dataclass(frozen=True)
class Settings:
    odoo_url: str
    odoo_db: str
    odoo_api_key: str
    odoo_username: str
    openrouter_api_key: str | None
    openrouter_model: str
    supabase_url: str
    supabase_service_role_key: str
    supabase_table: str
    odoo_admin_user_id: int | None

    @classmethod
    def from_env(cls) -> "Settings":
        odoo_url = _env("ODOO_URL")
        odoo_db = _env("ODOO_DB")
        odoo_api_key = _env("ODOO_API_KEY")
        odoo_username = _env("ODOO_USERNAME") or _env("ODOO_LOGIN")
        supabase_service_role_key = _env("SUPABASE_SERVICE_ROLE_KEY")
        supabase_url = _env("SUPABASE_URL")
        if not odoo_url or not odoo_db or not odoo_api_key or not odoo_username:
            raise ValueError(
                "ODOO_URL, ODOO_DB, ODOO_API_KEY, and ODOO_USERNAME are required"
            )
        if not supabase_service_role_key:
            raise ValueError("SUPABASE_SERVICE_ROLE_KEY is required")
        if not supabase_url:
            supabase_url = infer_supabase_url(supabase_service_role_key)
        return cls(
            odoo_url=odoo_url.rstrip("/"),
            odoo_db=odoo_db,
            odoo_api_key=odoo_api_key,
            odoo_username=odoo_username,
            openrouter_api_key=_env("OPENROUTER_API_KEY"),
            openrouter_model=_env("OPENROUTER_MODEL", "openai/gpt-4.1-mini") or "openai/gpt-4.1-mini",
            supabase_url=supabase_url.rstrip("/"),
            supabase_service_role_key=supabase_service_role_key,
            supabase_table=_env("SUPABASE_TABLE", "employees_module_contract_tracking")
            or "employees_module_contract_tracking",
            odoo_admin_user_id=int(_env("ODOO_ADMIN_USER_ID")) if _env("ODOO_ADMIN_USER_ID") else None,
        )

