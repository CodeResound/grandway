"""Domain exceptions for the search app.

Views translate these into the standard error envelope; nothing here subclasses
a DRF exception, so the domain layer stays free of HTTP concerns. This mirrors
``dashboards/exceptions.py`` — the app this one is modelled on.
"""

from __future__ import annotations


class SearchError(Exception):
    """Base for every error this app raises."""


class ActorNotPermittedError(SearchError):
    """The caller's authority may not use global search."""
