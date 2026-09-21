"""Shared runtime settings for the API (re-exported from the domain layer)."""

from academic_edge_domain.settings import Settings, get_settings, reset_settings_cache

__all__ = ["Settings", "get_settings", "reset_settings_cache"]
