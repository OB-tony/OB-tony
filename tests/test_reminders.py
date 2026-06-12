from __future__ import annotations

import datetime as dt
import unittest

from odoo_agent.odoo_client import is_allowed_model
from odoo_agent.reminders import run_contract_reminder


class FakeStore:
    def __init__(self, current_month=False):
        self.current_month = current_month
        self.marked = []

    def has_current_month_notification(self, employee_id, now):
        return self.current_month

    def mark_notified(self, employee_id, employee_name, contract_end_date, now):
        self.marked.append((employee_id, employee_name, contract_end_date, now))


class FakeOdoo:
    def __init__(self):
        self.creates = []
        self.sent = []

    def search_read(self, model, domain, fields, limit=None, order=None):
        if model == "hr.contract":
            return [
                {
                    "id": 10,
                    "name": "Contract A",
                    "employee_id": [1, "Alice"],
                    "date_end": "2026-06-20",
                }
            ]
        if model == "res.users":
            return [
                {
                    "id": 2,
                    "name": "Admin",
                    "email": "admin@example.com",
                    "login": "admin",
                    "partner_id": [7, "Admin Partner"],
                    "active": True,
                }
            ]
        if model == "mail.activity.type":
            return [{"id": 5, "name": "To Do"}]
        if model == "ir.model":
            return [{"id": 99}]
        raise AssertionError(f"Unexpected model {model}")

    def read(self, model, record_ids, fields):
        return [{"email": "admin@example.com"}]

    def create(self, model, values):
        self.creates.append((model, values))
        return 123

    def execute_kw(self, model, method, args=None, kwargs=None):
        self.sent.append((model, method, args, kwargs))
        return True


class ReminderTests(unittest.TestCase):
    def test_hr_model_allowlist(self):
        self.assertTrue(is_allowed_model("hr.employee"))
        self.assertTrue(is_allowed_model("hr.contract"))
        self.assertTrue(is_allowed_model("mail.activity"))
        self.assertFalse(is_allowed_model("sale.order"))

    def test_reminder_creates_activity_email_and_log(self):
        odoo = FakeOdoo()
        store = FakeStore(current_month=False)
        now = dt.datetime(2026, 6, 12, tzinfo=dt.timezone.utc)
        result = run_contract_reminder(odoo, store, now=now, window_days=30)
        self.assertEqual(result.scanned, 1)
        self.assertEqual(result.notified, 1)
        self.assertEqual(result.skipped, 0)
        self.assertEqual(len(store.marked), 1)
        self.assertEqual(odoo.creates[0][0], "mail.activity")
        self.assertEqual(odoo.creates[1][0], "mail.mail")

    def test_reminder_skips_current_month_duplicates(self):
        odoo = FakeOdoo()
        store = FakeStore(current_month=True)
        now = dt.datetime(2026, 6, 12, tzinfo=dt.timezone.utc)
        result = run_contract_reminder(odoo, store, now=now, window_days=30)
        self.assertEqual(result.notified, 0)
        self.assertEqual(result.skipped, 1)
        self.assertEqual(store.marked, [])
        self.assertEqual(odoo.creates, [])


if __name__ == "__main__":
    unittest.main()

