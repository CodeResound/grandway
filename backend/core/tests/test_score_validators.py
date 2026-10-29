"""The shared score, year, and language-test rules (2026-10-29).

Leads and applicants both rely on these, and conversion copies one into the
other — so a boundary moving here moves for both, and is pinned here once.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from unittest import mock

from django.test import SimpleTestCase

from core.validators import (
    academic_score_error,
    current_year,
    language_score_error,
    language_test_errors,
    year_error,
)


class LanguageScoreTests(SimpleTestCase):
    def test_ranges_and_steps(self) -> None:
        valid = [
            ("ielts", "0"),
            ("ielts", "9"),
            ("ielts", "6.5"),
            ("pte", "10"),
            ("pte", "90"),
            ("toefl", "0"),
            ("toefl", "120"),
            ("duolingo", "10"),
            ("duolingo", "160"),
            ("other", "999"),
        ]
        for test_type, value in valid:
            with self.subTest(test_type=test_type, value=value):
                self.assertIsNone(language_score_error(test_type, Decimal(value)))
        invalid = [
            ("ielts", "9.5"),
            ("ielts", "6.3"),
            ("pte", "9"),
            ("pte", "91"),
            ("toefl", "121"),
            ("duolingo", "9"),
            ("duolingo", "161"),
            ("other", "-1"),
        ]
        for test_type, value in invalid:
            with self.subTest(test_type=test_type, value=value):
                self.assertIsNotNone(language_score_error(test_type, Decimal(value)))

    def test_absent_score_is_fine(self) -> None:
        self.assertIsNone(language_score_error("ielts", None))


class AcademicScoreTests(SimpleTestCase):
    def test_gpa_and_percentage(self) -> None:
        self.assertIsNone(academic_score_error("gpa", Decimal("4.00")))
        self.assertIsNotNone(academic_score_error("gpa", Decimal("4.01")))
        self.assertIsNone(academic_score_error("percentage", Decimal("100")))
        self.assertIsNotNone(academic_score_error("percentage", Decimal("100.5")))


class YearTests(SimpleTestCase):
    @mock.patch("core.validators.nepal_today", return_value=date(2026, 10, 29))
    def test_bounds_follow_the_current_year(self, _today: mock.Mock) -> None:
        bs_now = current_year("bs")
        self.assertEqual(current_year("ad"), 2026)
        self.assertIsNone(year_error(2000, "bs"))
        self.assertIsNone(year_error(bs_now + 1, "bs"))
        self.assertIsNotNone(year_error(1999, "bs"))
        self.assertIsNotNone(year_error(bs_now + 2, "bs"))
        self.assertIsNone(year_error(1950, "ad"))
        self.assertIsNone(year_error(2027, "ad"))
        self.assertIsNotNone(year_error(2028, "ad"))
        self.assertIsNotNone(year_error(1949, "ad"))


class LanguageTestEntryTests(SimpleTestCase):
    def test_paths_name_each_failure(self) -> None:
        today = date.today()
        errors = language_test_errors(
            {
                "test_type": "ielts",
                "overall_score": Decimal("9.5"),
                "speaking_score": Decimal("6.3"),
                "test_date": today + timedelta(days=30),
                "expiry_date": today,
            },
            "language_tests[2]",
        )
        self.assertEqual(
            set(errors),
            {
                "language_tests[2].overall_score",
                "language_tests[2].speaking_score",
                "language_tests[2].test_date",
                "language_tests[2].expiry_date",
            },
        )

    def test_valid_entry(self) -> None:
        entry = {
            "test_type": "pte",
            "overall_score": Decimal("65"),
            "test_date": date(2025, 1, 1),
            "expiry_date": date(2027, 1, 1),
        }
        self.assertEqual(language_test_errors(entry, "x"), {})
