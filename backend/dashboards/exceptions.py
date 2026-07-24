"""Domain exceptions for the dashboards app.

Views translate these into the standard error envelope; nothing here subclasses
a DRF exception, so the domain layer stays free of HTTP concerns.
"""

from __future__ import annotations


class DashboardsError(Exception):
    """Base for every error this app raises."""


class ActorNotPermittedError(DashboardsError):
    """The caller's authority may not read the dashboard."""
