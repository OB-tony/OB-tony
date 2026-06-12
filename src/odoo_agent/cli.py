from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from typing import Any

from .config import Settings
from .intent import OpenRouterIntentParser, fallback_intent
from .odoo_client import OdooAccessError, OdooClient, is_allowed_model
from .reminders import run_contract_reminder
from .supabase_store import SupabaseStore


def _parse_json(value: str | None, default: Any) -> Any:
    if value is None:
        return default
    return json.loads(value)


def _confirm(prompt: str) -> bool:
    answer = input(f"{prompt} [y/N] ").strip().lower()
    return answer in {"y", "yes"}


def _print_rows(rows: list[dict[str, Any]]) -> None:
    for row in rows:
        print(json.dumps(row, ensure_ascii=True, default=str))


def _build_clients(settings: Settings) -> tuple[OdooClient, SupabaseStore]:
    return (
        OdooClient(settings.odoo_url, settings.odoo_db, settings.odoo_username, settings.odoo_api_key),
        SupabaseStore(settings.supabase_url, settings.supabase_service_role_key, settings.supabase_table),
    )


def _run_list(odoo: OdooClient, model: str, domain: list[Any], fields: list[str] | None) -> None:
    if not is_allowed_model(model):
        raise OdooAccessError(f"Model not allowed: {model}")
    rows = odoo.search_read(model, domain, fields or ["id", "name"])
    _print_rows(rows)


def _run_read(odoo: OdooClient, model: str, record_id: int, fields: list[str] | None) -> None:
    rows = odoo.read(model, [record_id], fields)
    _print_rows(rows)


def _run_create(odoo: OdooClient, model: str, values: dict[str, Any]) -> None:
    record_id = odoo.create(model, values)
    print(json.dumps({"id": record_id}, ensure_ascii=True))


def _run_update(odoo: OdooClient, model: str, record_id: int, values: dict[str, Any]) -> None:
    ok = odoo.write(model, [record_id], values)
    print(json.dumps({"updated": ok}, ensure_ascii=True))


def _run_delete(odoo: OdooClient, model: str, record_id: int) -> None:
    ok = odoo.unlink(model, [record_id])
    print(json.dumps({"deleted": ok}, ensure_ascii=True))


def _handle_record_command(args: argparse.Namespace, odoo: OdooClient) -> None:
    model = args.model
    if not is_allowed_model(model):
        raise OdooAccessError(f"Model not allowed: {model}")
    if args.command == "list":
        _run_list(odoo, model, _parse_json(args.domain, []), _parse_json(args.fields, None))
    elif args.command == "read":
        _run_read(odoo, model, args.id, _parse_json(args.fields, None))
    elif args.command == "create":
        _run_create(odoo, model, _parse_json(args.values, {}))
    elif args.command == "update":
        _run_update(odoo, model, args.id, _parse_json(args.values, {}))
    elif args.command == "delete":
        _run_delete(odoo, model, args.id)


def _handle_employee_command(args: argparse.Namespace, odoo: OdooClient) -> None:
    args.model = "hr.employee"
    _handle_record_command(args, odoo)


def _chat_loop(settings: Settings, odoo: OdooClient, store: SupabaseStore, prompt: str | None) -> None:
    parser = None
    if settings.openrouter_api_key:
        parser = OpenRouterIntentParser(settings.openrouter_api_key, settings.openrouter_model)
    if prompt:
        prompts = [prompt]
    else:
        prompts = []
        while True:
            try:
                text = input("odoo> ").strip()
            except EOFError:
                return
            if text in {"exit", "quit"}:
                return
            if text:
                prompts.append(text)
            else:
                continue
    for user_text in prompts:
        intent = None
        if parser:
            try:
                intent = parser.parse(user_text)
            except Exception:
                intent = fallback_intent(user_text)
        else:
            intent = fallback_intent(user_text)

        if intent.action == "help":
            print("Supported actions: list, read, create, update, delete, run_reminder")
            continue
        if intent.action == "run_reminder":
            result = run_contract_reminder(odoo, store, admin_user_id=settings.odoo_admin_user_id)
            print(json.dumps(result.__dict__, ensure_ascii=True))
            continue
        model = intent.model or "hr.employee"
        if not is_allowed_model(model):
            print(f"Rejected model: {model}")
            continue
        if intent.action in {"create", "update", "delete"}:
            if not _confirm(f"Execute {intent.action} on {model}?"):
                print("Skipped")
                continue
        if intent.action == "list":
            _run_list(odoo, model, intent.domain or [], intent.fields)
        elif intent.action == "read":
            if intent.record_id is None:
                print("Missing record_id")
                continue
            _run_read(odoo, model, intent.record_id, intent.fields)
        elif intent.action == "create":
            _run_create(odoo, model, intent.values or {})
        elif intent.action == "update":
            if intent.record_id is None:
                print("Missing record_id")
                continue
            _run_update(odoo, model, intent.record_id, intent.values or {})
        elif intent.action == "delete":
            if intent.record_id is None:
                print("Missing record_id")
                continue
            _run_delete(odoo, model, intent.record_id)
        else:
            print(f"Unsupported action: {intent.action}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="odoo-hr-agent")
    sub = parser.add_subparsers(dest="top", required=True)

    chat = sub.add_parser("chat", help="Interactive or one-shot natural language mode")
    chat.add_argument("prompt", nargs="?", help="One-shot prompt")

    reminder = sub.add_parser("reminder", help="Reminder operations")
    reminder_sub = reminder.add_subparsers(dest="command", required=True)
    reminder_run = reminder_sub.add_parser("run", help="Run the monthly contract reminder")
    reminder_run.add_argument("--window-days", type=int, default=30)

    record = sub.add_parser("record", help="Generic CRUD for allowed models")
    record.add_argument("command", choices=["list", "read", "create", "update", "delete"])
    record.add_argument("--model", required=True)
    record.add_argument("--id", type=int)
    record.add_argument("--domain")
    record.add_argument("--fields")
    record.add_argument("--values")

    employee = sub.add_parser("employee", help="CRUD on hr.employee")
    employee.add_argument("command", choices=["list", "read", "create", "update", "delete"])
    employee.add_argument("--id", type=int)
    employee.add_argument("--domain")
    employee.add_argument("--fields")
    employee.add_argument("--values")

    return parser


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    parser = build_parser()
    args = parser.parse_args(argv)
    settings = Settings.from_env()
    odoo, store = _build_clients(settings)

    try:
        if args.top == "chat":
            _chat_loop(settings, odoo, store, args.prompt)
        elif args.top == "reminder" and args.command == "run":
            result = run_contract_reminder(
                odoo,
                store,
                window_days=args.window_days,
                admin_user_id=settings.odoo_admin_user_id,
            )
            print(json.dumps(result.__dict__, ensure_ascii=True))
        elif args.top == "record":
            _handle_record_command(args, odoo)
        elif args.top == "employee":
            _handle_employee_command(args, odoo)
        else:
            parser.print_help()
            return 1
    except OdooAccessError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

