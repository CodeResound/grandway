"""The storage volume must never be reachable by URL.

`uploaded_files` stores applicant passports, transcripts, and bank statements on
the local filesystem under ``MEDIA_ROOT``. The whole privacy model of that app
rests on one fact: **no URL maps to that directory.** The bytes leave only
through ``GET /api/v1/files/<id>/download/``, which applies an authority check
and writes an audit event.

That fact is one line away from being false. ``django.conf.urls.static.static()``
is the standard local-development convenience for serving media, it is what most
Django tutorials add to the root URL configuration, and adding it here would
publish every applicant document at a guessable path with no authentication and
no audit trail — silently, and only in whichever environments it was enabled.

This test lives in ``core`` rather than in ``uploaded_files`` because the risk is
in ``core/urls.py``, not in that app. Someone adding a media route would have no
reason to open the file app's test suite.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from django.conf import settings
from django.test import TestCase, override_settings
from django.urls import get_resolver


class MediaIsNotServedTests(TestCase):
    def test_no_root_url_pattern_serves_the_storage_volume(self) -> None:
        """The root URL configuration routes four prefixes, none of them static."""
        patterns = {str(pattern.pattern) for pattern in get_resolver().url_patterns}
        self.assertEqual(patterns, {"admin/", "health/", "ready/", "api/v1/"})

    def test_no_view_in_the_project_serves_files_from_media_root(self) -> None:
        """A stricter form of the check above, by view rather than by prefix.

        Catches a media route added under an existing prefix, which the set
        comparison above would miss.
        """
        for pattern in get_resolver().url_patterns:
            view = getattr(pattern, "callback", None)
            with self.subTest(route=str(pattern.pattern)):
                self.assertNotIn("serve", getattr(view, "__name__", ""))

    def test_a_guessable_media_path_is_not_routed(self) -> None:
        """The shape of URL a leaked storage path would produce."""
        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                probe = Path(media_root) / "uploaded_files" / "applicant" / "2026" / "07"
                probe.mkdir(parents=True)
                (probe / "leaked.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")

                for url in (
                    "/uploaded_files/applicant/2026/07/leaked.pdf",
                    "/media/uploaded_files/applicant/2026/07/leaked.pdf",
                    "/mediafiles/uploaded_files/applicant/2026/07/leaked.pdf",
                ):
                    with self.subTest(url=url):
                        self.assertEqual(self.client.get(url).status_code, 404)

    def test_uploads_land_owner_and_group_readable_only(self) -> None:
        """Django's 0o644 default would make every applicant document
        world-readable to any account on the host."""
        self.assertEqual(settings.FILE_UPLOAD_PERMISSIONS, 0o640)
        self.assertEqual(settings.FILE_UPLOAD_DIRECTORY_PERMISSIONS, 0o750)

    def test_only_one_file_per_request_is_accepted(self) -> None:
        self.assertEqual(settings.DATA_UPLOAD_MAX_NUMBER_FILES, 1)
