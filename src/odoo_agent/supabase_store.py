from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from typing import Any
from urllib import parse, request


@dataclass(frozen=True)
class ReminderRow:
    employee_id: int
    employee_name: str
    contract_end_date: str
    notification_sent: bool
    sent_timestamp: str


class SupabaseStore:
    def __init__(self, url: str, service_role_key: str, table: str) -> None:
        self.url = url.rstrip("/")
        self.key = service_role_key
        self.table = table

    def _headers(self) -> dict[str, str]:
        return {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates,return=representation",
        }

    def _request(self, method: str, path: str, body: Any | None = None, query: dict[str, str] | None = None) -> Any:
        url = f"{self.url}{path}"
        if query:
            url = f"{url}?{parse.urlencode(query)}"
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = request.Request(url, data=data, headers=self._headers(), method=method)
        with request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else None

    def get_by_employee_id(self, employee_id: int) -> dict[str, Any] | None:
        rows = self._request(
            "GET",
            f"/rest/v1/{self.table}",
            query={
                "employee_id": f"eq.{employee_id}",
                "select": "employee_id,employee_name,contract_end_date,notification_sent,sent_timestamp",
                "limit": "1",
            },
        )
        if not rows:
            return None
        return rows[0]

    @staticmethod
    def _current_period(now: dt.datetime) -> str:
        return now.strftime("%Y-%m")

    def has_current_month_notification(self, employee_id: int, now: dt.datetime) -> bool:
        row = self.get_by_employee_id(employee_id)
        if not row:
            return False
        if not row.get("notification_sent"):
            return False
        sent_timestamp = row.get("sent_timestamp")
        if not sent_timestamp:
            return False
        try:
            sent_dt = dt.datetime.fromisoformat(sent_timestamp.replace("Z", "+00:00"))
        except ValueError:
            return False
        return self._current_period(sent_dt) == self._current_period(now)

    def upsert_reminder(self, row: ReminderRow) -> Any:
        body = {
            "employee_id": row.employee_id,
            "employee_name": row.employee_name,
            "contract_end_date": row.contract_end_date,
            "notification_sent": row.notification_sent,
            "sent_timestamp": row.sent_timestamp,
        }
        return self._request(
            "POST",
            f"/rest/v1/{self.table}",
            body=body,
            query={"on_conflict": "employee_id"},
        )

    def mark_notified(self, employee_id: int, employee_name: str, contract_end_date: str, now: dt.datetime) -> Any:
        row = ReminderRow(
            employee_id=employee_id,
            employee_name=employee_name,
            contract_end_date=contract_end_date,
            notification_sent=True,
            sent_timestamp=now.replace(microsecond=0).isoformat(),
        )
        return self.upsert_reminder(row)
