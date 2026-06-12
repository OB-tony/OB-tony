from __future__ import annotations

import xmlrpc.client
from dataclasses import dataclass
from typing import Any


class OdooAccessError(RuntimeError):
    pass


ALLOWED_PREFIXES = ("hr.",)
ALLOWED_MODELS = {
    "mail.activity",
    "mail.activity.type",
    "mail.mail",
    "mail.message",
    "mail.notification",
    "res.partner",
    "res.users",
    "ir.model",
}


def is_allowed_model(model: str) -> bool:
    return model.startswith(ALLOWED_PREFIXES) or model in ALLOWED_MODELS


@dataclass
class OdooClient:
    url: str
    db: str
    username: str
    api_key: str

    def __post_init__(self) -> None:
        self._common = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/common")
        self._object = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/object")
        self._uid: int | None = None

    @property
    def uid(self) -> int:
        if self._uid is None:
            uid = self._common.authenticate(self.db, self.username, self.api_key, {})
            if not uid:
                raise RuntimeError("Odoo authentication failed")
            self._uid = uid
        return self._uid

    def _ensure_allowed(self, model: str) -> None:
        if not is_allowed_model(model):
            raise OdooAccessError(f"Model not allowed: {model}")

    def execute_kw(self, model: str, method: str, args: list[Any] | None = None, kwargs: dict[str, Any] | None = None) -> Any:
        self._ensure_allowed(model)
        return self._object.execute_kw(self.db, self.uid, self.api_key, model, method, args or [], kwargs or {})

    def search(self, model: str, domain: list[Any], *, limit: int | None = None, order: str | None = None) -> list[int]:
        kwargs: dict[str, Any] = {}
        if limit is not None:
            kwargs["limit"] = limit
        if order is not None:
            kwargs["order"] = order
        return list(self.execute_kw(model, "search", [domain], kwargs))

    def search_read(
        self,
        model: str,
        domain: list[Any],
        fields: list[str] | None = None,
        *,
        limit: int | None = None,
        order: str | None = None,
    ) -> list[dict[str, Any]]:
        kwargs: dict[str, Any] = {}
        if fields is not None:
            kwargs["fields"] = fields
        if limit is not None:
            kwargs["limit"] = limit
        if order is not None:
            kwargs["order"] = order
        return list(self.execute_kw(model, "search_read", [domain], kwargs))

    def read(self, model: str, record_ids: list[int], fields: list[str] | None = None) -> list[dict[str, Any]]:
        kwargs: dict[str, Any] = {}
        if fields is not None:
            kwargs["fields"] = fields
        return list(self.execute_kw(model, "read", [record_ids], kwargs))

    def create(self, model: str, values: dict[str, Any]) -> int:
        return int(self.execute_kw(model, "create", [values]))

    def write(self, model: str, record_ids: list[int], values: dict[str, Any]) -> bool:
        return bool(self.execute_kw(model, "write", [record_ids, values]))

    def unlink(self, model: str, record_ids: list[int]) -> bool:
        return bool(self.execute_kw(model, "unlink", [record_ids]))


def resolve_admin_user(odoo: OdooClient, admin_user_id: int | None = None) -> dict[str, Any]:
    if admin_user_id:
        users = odoo.read("res.users", [admin_user_id], ["name", "email", "login", "partner_id", "active"])
        if users:
            return users[0]
    candidates = odoo.search_read(
        "res.users",
        ["|", ("login", "=", "admin"), ("name", "ilike", "admin")],
        ["name", "email", "login", "partner_id", "active"],
        limit=10,
        order="id asc",
    )
    for candidate in candidates:
        if candidate.get("active", True):
            return candidate
    raise RuntimeError("Could not resolve admin user")

