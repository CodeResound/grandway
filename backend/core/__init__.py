"""Grandway backend — application version identity (CLAUDE.md §41.2).

The repo-root VERSION file is canonical: release tooling, CI, and external
consumers need the version without importing Django settings, so the file is
read here rather than the constant being the source of truth. The literal
fallback keeps the package importable if the file is missing (an installed
copy without the repo root, for instance) — it is a last resort, not a second
source of truth, and CI asserts VERSION == tag == __version__ at release time.
"""

from pathlib import Path

_VERSION_FILE = Path(__file__).resolve().parents[2] / "VERSION"

try:
    __version__ = _VERSION_FILE.read_text(encoding="utf-8").strip()
except OSError:  # pragma: no cover — only when the repo root is absent
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
