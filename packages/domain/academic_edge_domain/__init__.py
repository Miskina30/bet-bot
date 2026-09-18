"""Canonical domain layer for Academic Edge.

Public surface kept deliberately small: import submodules directly
(``academic_edge_domain.models``, ``.settings``, ``.policy``) so that importing
the domain does not drag in YAML parsing, SQLAlchemy engines or settings.
"""
