"""Personal clipboard — /api/v1/auth/me/clipboard/ (2026-10-29, frontend updates.md §5).

Every account has one, Superadmin included, and nobody can reach another's.
These pin the isolation (404, never 403), the categories each person runs for
themselves, ranking by use, the limits, and that the text never reaches the
audit trail.
"""

from __future__ import annotations

from typing import Any

from audit.models import AuditEvent
from django.urls import reverse
from rest_framework.test import APITestCase

from authenticate import services
from authenticate.constants import MAX_CLIPBOARD_CATEGORIES, MAX_CLIPBOARD_ENTRIES, AuthorityType, ErrorCode
from authenticate.models import ClipboardCategory, ClipboardEntry
from authenticate.tests.test_accounts import make, token_for

LIST_URL = reverse("v1:auth:clipboard-list")
CATEGORIES_URL = reverse("v1:auth:clipboard-category-list")


def entry_url(entry_id: Any, action: str = "") -> str:
    if action == "use":
        return reverse("v1:auth:clipboard-use", args=[entry_id])
    return reverse("v1:auth:clipboard-detail", args=[entry_id])


def category_url(category_id: Any) -> str:
    return reverse("v1:auth:clipboard-category-detail", args=[category_id])


class _Clipboard(APITestCase):
    def setUp(self) -> None:
        self.me = make("leadmgr", AuthorityType.LEAD_MANAGER)
        self.other = make("othermgr", AuthorityType.LEAD_MANAGER)
        self.act_as(self.me)

    def act_as(self, user: Any) -> None:
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token_for(user)}")

    def save(self, label: str = "Ward 7 chairman", text: str = "Ram Bahadur Thapa", **extra: Any) -> Any:
        return self.client.post(LIST_URL, {"label": label, "text": text, **extra}, format="json")

    def rows(self, **params: Any) -> list[dict[str, Any]]:
        response = self.client.get(LIST_URL, params)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()["data"]


class EntryTests(_Clipboard):
    def test_every_authority_has_a_working_clipboard(self) -> None:
        for authority in (AuthorityType.SUPERADMIN, AuthorityType.ADMIN, AuthorityType.LEAD_MANAGER):
            with self.subTest(authority=authority):
                self.act_as(make(f"user_{authority}", authority))
                created = self.save(field_key="ward.spokesperson.name")
                self.assertEqual(created.status_code, 201, created.content)
                entry = created.json()["data"]
                self.assertEqual(entry["field_key"], "ward.spokesperson.name")
                self.assertIsNone(entry["category"])
                patched = self.client.patch(entry_url(entry["id"]), {"text": "Hari Thapa"}, format="json")
                self.assertEqual(patched.json()["data"]["text"], "Hari Thapa")
                self.assertEqual([r["id"] for r in self.rows()], [entry["id"]])
                deleted = self.client.delete(entry_url(entry["id"]))
                self.assertEqual(deleted.json()["data"], {"deleted": True})
                self.assertEqual(self.rows(), [])

    def test_another_accounts_entry_is_invisible(self) -> None:
        self.act_as(self.other)
        theirs = self.save().json()["data"]["id"]
        self.act_as(self.me)
        self.assertEqual(self.rows(), [])
        for response in (
            self.client.patch(entry_url(theirs), {"text": "x"}, format="json"),
            self.client.delete(entry_url(theirs)),
            self.client.post(entry_url(theirs, "use")),
        ):
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json()["error"]["code"], ErrorCode.CLIPBOARD_ENTRY_NOT_FOUND)
        self.assertEqual(ClipboardEntry.objects.get(pk=theirs).text, "Ram Bahadur Thapa")

    def test_filters(self) -> None:
        self.save("Father", "Hari", field_key="father.name")
        self.save("Mother", "Gita", field_key="mother.name")
        self.save("Bank", "0123456789", field_key="bank.account_no")
        self.assertEqual({r["label"] for r in self.rows(field_key="father.name,mother.name")}, {"Father", "Mother"})
        self.assertEqual({r["label"] for r in self.rows(search="gita")}, {"Mother"})
        self.assertEqual(self.client.get(LIST_URL, {"field_key": "Father Name"}).status_code, 400)

    def test_use_ranks_entries(self) -> None:
        first = self.save("First", "a").json()["data"]["id"]
        second = self.save("Second", "b").json()["data"]["id"]
        self.save("Never used", "c")
        used = self.client.post(entry_url(second, "use")).json()["data"]
        self.assertEqual(used["usage_count"], 1)
        self.assertIsNotNone(used["last_used_at"])
        self.client.post(entry_url(second, "use"))
        self.client.post(entry_url(first, "use"))
        self.assertEqual([r["label"] for r in self.rows()], ["Second", "First", "Never used"])

    def test_validation_and_normalization(self) -> None:
        self.assertEqual(self.save(text="x" * 2001).status_code, 400)
        self.assertEqual(self.save(label="   ").status_code, 400)
        self.assertEqual(self.save(text="").status_code, 400)
        self.assertEqual(self.save(field_key="Bad Key").status_code, 400)
        decomposed = "Café"
        entry = self.save(label=decomposed).json()["data"]
        self.assertEqual(entry["label"], "Café")

    def test_entry_limit(self) -> None:
        ClipboardEntry.objects.bulk_create(
            ClipboardEntry(user=self.me, label=f"e{i}", text="t") for i in range(MAX_CLIPBOARD_ENTRIES)
        )
        response = self.save()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], ErrorCode.CLIPBOARD_LIMIT_REACHED)
        self.act_as(self.other)
        self.assertEqual(self.save().status_code, 201)  # the cap is per account

    def test_audit_never_holds_the_text_or_label(self) -> None:
        entry = self.save("Citizenship", "27-01-75-12345").json()["data"]["id"]
        self.client.patch(entry_url(entry), {"text": "27-01-75-99999"}, format="json")
        self.client.post(entry_url(entry, "use"))
        self.client.delete(entry_url(entry))
        events = AuditEvent.objects.filter(entity_id=entry)
        self.assertEqual(
            sorted(events.values_list("action", flat=True)),
            ["clipboard_entry_created", "clipboard_entry_deleted", "clipboard_entry_updated"],
        )
        dump = " ".join(f"{e.summary} {e.changes} {e.metadata}" for e in events)
        for secret in ("12345", "99999", "Citizenship"):
            self.assertNotIn(secret, dump)

    def test_a_failed_audit_write_rolls_the_change_back(self) -> None:
        from unittest import mock

        entry = self.save().json()["data"]["id"]
        with mock.patch("audit.services.AuditEvent.objects.create", side_effect=RuntimeError("audit down")):
            for call in (
                lambda: services.update_clipboard_entry(
                    user=self.me, entry=ClipboardEntry.objects.get(pk=entry), fields={"text": "changed"}
                ),
                lambda: services.delete_clipboard_entry(user=self.me, entry=ClipboardEntry.objects.get(pk=entry)),
            ):
                with self.assertRaises(RuntimeError):
                    call()
        self.assertEqual(ClipboardEntry.objects.get(pk=entry).text, "Ram Bahadur Thapa")

    def test_unauthenticated(self) -> None:
        self.client.credentials()
        self.assertEqual(self.client.get(LIST_URL).status_code, 401)


class CategoryTests(_Clipboard):
    def make_category(self, name: str) -> Any:
        return self.client.post(CATEGORIES_URL, {"name": name}, format="json")

    def test_create_rename_list_with_counts(self) -> None:
        bank = self.make_category("Bank").json()["data"]
        ward = self.make_category("Ward office").json()["data"]
        self.save("Account", "0123", category=bank["id"])
        self.save("Chairman", "Ram", category=bank["id"])
        renamed = self.client.patch(category_url(ward["id"]), {"name": "Woda"}, format="json")
        self.assertEqual(renamed.json()["data"]["name"], "Woda")
        listed = self.client.get(CATEGORIES_URL).json()["data"]
        self.assertEqual([(c["name"], c["entry_count"]) for c in listed], [("Bank", 2), ("Woda", 0)])

    def test_names_are_unique_per_account_ignoring_case(self) -> None:
        self.make_category("Bank")
        response = self.make_category("bank")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], ErrorCode.CLIPBOARD_CATEGORY_NAME_TAKEN)
        other = self.make_category("Other").json()["data"]["id"]
        self.assertEqual(
            self.client.patch(category_url(other), {"name": "BANK"}, format="json").json()["error"]["code"],
            ErrorCode.CLIPBOARD_CATEGORY_NAME_TAKEN,
        )
        self.act_as(self.other)
        self.assertEqual(self.make_category("Bank").status_code, 201)

    def test_category_limit(self) -> None:
        ClipboardCategory.objects.bulk_create(
            ClipboardCategory(user=self.me, name=f"c{i}") for i in range(MAX_CLIPBOARD_CATEGORIES)
        )
        response = self.make_category("One more")
        self.assertEqual(response.json()["error"]["code"], ErrorCode.CLIPBOARD_CATEGORY_LIMIT_REACHED)

    def test_delete_keeps_entries_uncategorized(self) -> None:
        bank = self.make_category("Bank").json()["data"]["id"]
        entry = self.save(category=bank).json()["data"]["id"]
        response = self.client.delete(category_url(bank))
        self.assertEqual(response.json()["data"], {"deleted": True, "entries_uncategorized": 1})
        self.assertIsNone(ClipboardEntry.objects.get(pk=entry).category)

    def test_filters_by_category_and_search_matches_its_name(self) -> None:
        bank = self.make_category("Bank").json()["data"]["id"]
        self.save("Account", "0123", category=bank)
        self.save("Chairman", "Ram")
        self.assertEqual([r["label"] for r in self.rows(category=bank)], ["Account"])
        self.assertEqual([r["label"] for r in self.rows(category="none")], ["Chairman"])
        self.assertEqual([r["label"] for r in self.rows(search="bank")], ["Account"])
        self.assertEqual(self.client.get(LIST_URL, {"category": "banks"}).status_code, 400)

    def test_moving_and_clearing_an_entrys_category(self) -> None:
        bank = self.make_category("Bank").json()["data"]["id"]
        entry = self.save().json()["data"]["id"]
        moved = self.client.patch(entry_url(entry), {"category": bank}, format="json").json()["data"]
        self.assertEqual(moved["category"]["name"], "Bank")
        cleared = self.client.patch(entry_url(entry), {"category": None}, format="json").json()["data"]
        self.assertIsNone(cleared["category"])

    def test_another_accounts_category(self) -> None:
        self.act_as(self.other)
        theirs = self.make_category("Theirs").json()["data"]["id"]
        self.act_as(self.me)
        self.assertEqual(self.client.get(CATEGORIES_URL).json()["data"], [])
        for response in (
            self.client.patch(category_url(theirs), {"name": "Mine"}, format="json"),
            self.client.delete(category_url(theirs)),
        ):
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json()["error"]["code"], ErrorCode.CLIPBOARD_CATEGORY_NOT_FOUND)
        response = self.save(category=theirs)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], ErrorCode.CLIPBOARD_CATEGORY_INVALID)

    def test_category_audit_never_holds_the_name(self) -> None:
        category = services.create_clipboard_category(user=self.me, name="Rita's citizenship")
        services.delete_clipboard_category(user=self.me, category=category)
        dump = " ".join(
            f"{e.summary} {e.metadata}"
            for e in AuditEvent.objects.filter(entity_type="authenticate.clipboard_category")
        )
        self.assertNotIn("Rita", dump)
