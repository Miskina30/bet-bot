"""Provider connector layer for Academic Edge (importable package).

Public entry point is :func:`academic_edge_connectors.registry.build_adapter`;
the module-level exports are completed at the bottom of this file.

Nothing in this package places bets, signs transactions or holds credentials
beyond the read-only provider keys supplied through ``Settings``.
"""

from __future__ import annotations

__all__: list[str] = []
