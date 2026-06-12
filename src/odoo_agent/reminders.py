from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

from .odoo_client import OdooClient, resolve_admin_user
from .supabase_store import SupabaseStore


@dataclass(frozen=True)
class ReminderResult:
    scanned: int
    notified: int
    skipped: int


def _to_date_string(value: Any) -> str:
    if isinstance(value, dt.date):
        return value.isoformat()
    return str(value)


def _contract_domain(window_start: dt.date, window_end: dt.date) -> list[Any]:
    return [
        ("state", "=", "open"),
        ("date_end", "!=", False),
        ("date_end", ">=", window_start.isoformat()),
        ("date_end", "<=", window_end.isoformat()),
    ]


def _get_default_activity_type(odoo: OdooClient) -> int:
    rows = odoo.search_read(
        "mail.activity.type",
        [("name", "ilike", "todo")],
        ["id", "name"],
        limit=1,
    )
    if rows:
        return int(rows[0]["id"])
    rows = odoo.search_read("mail.activity.type", [], ["id", "name"], limit=1)
    if not rows:
        raise RuntimeError("Could not find a mail.activity.type")
    return int(rows[0]["id"])


def _create_admin_activity(
    odoo: OdooClient,
    contract_id: int,
    admin_user_id: int,
    summary: str,
    note: str,
    deadline: dt.date,
) -> None:
    activity_type_id = _get_default_activity_type(odoo)
    model_ids = odoo.search_read(
        "ir.model",
        [("model", "=", "hr.contract")],
        ["id"],
        limit=1,
    )
    if not model_ids:
        raise RuntimeError("Could not resolve hr.contract model id")
    odoo.create(
        "mail.activity",
        {
            "activity_type_id": activity_type_id,
            "res_model_id": int(model_ids[0]["id"]),
            "res_id": contract_id,
            "user_id": admin_user_id,
            "date_deadline": deadline.isoformat(),
            "summary": summary,
            "note": note,
        },
    )


def _send_admin_email(odoo: OdooClient, admin_email: str, subject: str, body_html: str) -> None:
    if not admin_email:
        raise RuntimeError("Admin user email is missing")
    mail_id = odoo.create(
        "mail.mail",
        {
            "subject": subject,
            "body_html": body_html,
            "email_to": admin_email,
        },
    )
    odoo.execute_kw("mail.mail", "send", [[mail_id]])


def run_contract_reminder(
    odoo: OdooClient,
    store: SupabaseStore,
    *,
    now: dt.datetime | None = None,
    window_days: int = 30,
    admin_user_id: int | None = None,
) -> ReminderResult:
    now = now or dt.datetime.now(dt.timezone.utc)
    window_start = now.date()
    window_end = (now + dt.timedelta(days=window_days)).date()
    contracts = odoo.search_read(
        "hr.contract",
        _contract_domain(window_start, window_end),
        ["id", "name", "employee_id", "date_end"],
        order="date_end asc",
    )

    admin_user = resolve_admin_user(odoo, admin_user_id)
    email = admin_user.get("email") or ""
    if not email and isinstance(admin_user.get("partner_id"), list) and len(admin_user["partner_id"]) >= 2:
        partner_id = int(admin_user["partner_id"][0])
        partner = odoo.read("res.partner", [partner_id], ["email"])
        if partner:
            email = partner[0].get("email") or ""

    notified = 0
    skipped = 0

    for contract in contracts:
        employee = contract.get("employee_id")
        if not isinstance(employee, list) or len(employee) < 2:
            continue
        employee_id = int(employee[0])
        employee_name = str(employee[1])
        end_date = _to_date_string(contract.get("date_end") or "")
        if store.has_current_month_notification(employee_id, now):
            skipped += 1
            continue

        summary = f"Contract expiring soon: {employee_name}"
        note = (
            f"Employee contract for {employee_name} is scheduled to end on {end_date}."
            f" Please review contract status before expiry."
        )
        _create_admin_activity(
            odoo,
            int(contract["id"]),
            int(admin_user["id"]),
            summary,
            note,
            window_start,
        )
        _send_admin_email(
            odoo,
            email,
            subject=summary,
            body_html=f"<p>{note}</p><p>Contract ID: {contract['id']}</p>",
        )
        store.mark_notified(employee_id, employee_name, end_date, now)
        notified += 1

    return ReminderResult(scanned=len(contracts), notified=notified, skipped=skipped)
