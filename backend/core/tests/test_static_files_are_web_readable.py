"""Collected static files must be readable by the web server user.

nginx serves ``STATIC_ROOT`` directly off the disk as ``www-data`` (deploy.md §9),
and ``www-data`` is deliberately kept out of the application's group so that a
mistaken ``alias`` can never reach ``MEDIA_ROOT`` (deploy.md §5). That leaves
nginx with *only* the world bits on every static file and directory.

Django makes this easy to get wrong. ``FILE_UPLOAD_PERMISSIONS`` and
``FILE_UPLOAD_DIRECTORY_PERMISSIONS`` read as upload-only, but
``StaticFilesStorage`` subclasses ``FileSystemStorage`` and inherits both — so
this project's ``0640``/``0750``, which exist to protect applicant passports,
silently applied to ``collectstatic`` output as well. Every asset landed owner-
and-group-only and nginx returned 403 for the whole tree: the admin rendered
unstyled with dead JavaScript, while the API, whose renderers are JSON-only,
looked perfectly healthy.

The failure is invisible in development, where ``runserver`` serves static from
the application directories and never reads ``STATIC_ROOT`` at all. So this test
does the one thing that actually catches it: it runs ``collectstatic`` and looks
at the resulting modes. Asserting on the ``STORAGES`` setting instead would pass
for any future backend that reintroduces the same behaviour by another route.
"""

from __future__ import annotations

import stat
import tempfile
from pathlib import Path

from django.core.files.storage import default_storage
from django.core.management import call_command
from django.test import SimpleTestCase, override_settings

WORLD_READ = stat.S_IROTH
WORLD_READ_AND_TRAVERSE = stat.S_IROTH | stat.S_IXOTH


class CollectedStaticFilesTests(SimpleTestCase):
    def test_collectstatic_output_is_world_readable(self) -> None:
        """Every collected file and every directory holding one."""
        with tempfile.TemporaryDirectory() as tmp:
            static_root = Path(tmp) / "static"
            with override_settings(STATIC_ROOT=static_root):
                call_command("collectstatic", "--noinput", verbosity=0)

            collected = sorted(static_root.rglob("*"))
            self.assertTrue(collected, "collectstatic produced no files")

            for path in [static_root, *collected]:
                mode = stat.S_IMODE(path.stat().st_mode)
                required = WORLD_READ_AND_TRAVERSE if path.is_dir() else WORLD_READ
                with self.subTest(path=path.relative_to(static_root.parent)):
                    self.assertEqual(
                        mode & required,
                        required,
                        f"{path} is {oct(mode)}; nginx runs as a user in neither the "
                        f"owner nor the group and cannot read it",
                    )

    def test_uploads_are_still_owner_and_group_only(self) -> None:
        """The other half of the fix: loosening static must not loosen media.

        ``STORAGES["default"]`` passes no permission options, so the default
        backend still falls back to ``FILE_UPLOAD_PERMISSIONS``.
        """
        self.assertEqual(default_storage.file_permissions_mode, 0o640)
        self.assertEqual(default_storage.directory_permissions_mode, 0o750)

    def test_the_two_volumes_do_not_share_a_permission_mode(self) -> None:
        """A regression guard with a shape the reader can check at a glance."""
        from django.contrib.staticfiles.storage import staticfiles_storage

        self.assertEqual(staticfiles_storage.file_permissions_mode, 0o644)
        self.assertEqual(staticfiles_storage.directory_permissions_mode, 0o755)
        self.assertNotEqual(
            staticfiles_storage.file_permissions_mode,
            default_storage.file_permissions_mode,
        )
