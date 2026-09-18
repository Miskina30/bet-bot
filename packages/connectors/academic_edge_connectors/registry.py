"""Adapter factory: one place that turns a source id into a working adapter.

The factory is where policy meets construction:

* unknown source ids raise :class:`PolicyViolation` (add a registry entry first);
* ``live`` mode requires credentials where the vendor demands them, and always
  goes through ``SourcePolicyRegistry.require_live_client`` via the HTTP client;
* Crocobet has no live path at all in this build: ``build_adapter("crocobet")``
  always returns the manual-CSV adapter, and any live request for it raises
  :class:`PolicyViolation`;
* ``fixture`` mode needs no keys, no network and no policy exceptions, and
  every record it produces is labelled synthetic.
"""

from __future__ import annotations

from typing import Any

from academic_edge_domain.enums import AutomationScope
from academic_edge_domain.policy import PolicyViolation, SourcePolicyRegistry
from academic_edge_domain.settings import Settings

from academic_edge_connectors.api_football import ApiFootballAdapter
from academic_edge_connectors.crocobet_csv import CrocobetManualCsvAdapter as CrocobetCsvAdapter
from academic_edge_connectors.football_data_org import FootballDataOrgAdapter
from academic_edge_connectors.football_data_uk import FootballDataUkAdapter
from academic_edge_connectors.http import FIXTURE_MODE, LIVE_MODE
from academic_edge_connectors.polymarket import PolymarketAdapter

_NO_NETWORK_SOURCES = frozenset({"football_data_org"})  # no odds marketplace


def available_sources(registry: SourcePolicyRegistry) -> list[str]:
    """Source ids this build can construct an adapter for."""
    return [
        "api_football",
        "football_data_org",
        "polymarket_gamma",
        "football_data_uk",
        "crocobet",
    ]


def build_adapter(
    source_id: str,
    settings: Settings | None = None,
    policy_registry: SourcePolicyRegistry | None = None,
    *,
    mode: str = FIXTURE_MODE,
    **kwargs: Any,
) -> Any:
    """Construct the adapter for ``source_id`` in ``mode``.

    ``mode`` is ``"live"`` or ``"fixture"``. Unknown source ids, live requests
    for manual-only sources, and live adapters without the required credential
    all fail loudly instead of degrading silently.
    """
    from academic_edge_domain.policy import load_registry

    if mode not in {LIVE_MODE, FIXTURE_MODE}:
        raise ValueError(f"mode must be 'live' or 'fixture', got {mode!r}")
    cfg = settings if settings is not None else Settings()
    registry = policy_registry if policy_registry is not None else load_registry()

    if source_id == "api_football":
        return ApiFootballAdapter(cfg, registry, mode=mode, **kwargs)
    if source_id == "football_data_org":
        return FootballDataOrgAdapter(cfg, registry, mode=mode, **kwargs)
    if source_id in {"polymarket_gamma", "polymarket_clob"}:
        return PolymarketAdapter(cfg, registry, mode=mode, **kwargs)
    if source_id == "football_data_uk":
        return FootballDataUkAdapter(cfg, registry, mode=mode, **kwargs)
    if source_id == "crocobet":
        registry.require_manual_import("crocobet")
        if mode != FIXTURE_MODE:
            raise PolicyViolation(
                "crocobet has no live path in this build: manual CSV only. "
                "Pass mode='fixture' with an operator-supplied export."
            )
        return CrocobetCsvAdapter(registry, settings=cfg, **kwargs)

    raise PolicyViolation(
        f"source {source_id!r} has no adapter. Add it to config/source_policies.yaml "
        "and register it here before use."
    )


def build_fixture_adapters(
    settings: Settings | None = None,
    policy_registry: SourcePolicyRegistry | None = None,
) -> dict[str, Any]:
    """Every adapter in fixture mode: the keyless demo / test harness."""
    return {
        source_id: build_adapter(source_id, settings, policy_registry, mode=FIXTURE_MODE)
        for source_id in available_sources(
            policy_registry if policy_registry is not None else _registry(settings)
        )
    }


def _registry(settings: Settings | None) -> SourcePolicyRegistry:
    from academic_edge_domain.policy import load_registry

    return load_registry()


def adapter_mode_summary(settings: Settings) -> dict[str, str]:
    """Which mode each source would run in, given the current settings."""
    summary: dict[str, str] = {
        "api_football": LIVE_MODE if settings.api_football_key else FIXTURE_MODE,
        "football_data_org": LIVE_MODE if settings.football_data_org_token else FIXTURE_MODE,
        "polymarket_gamma": LIVE_MODE if settings.polymarket_enabled else FIXTURE_MODE,
        "football_data_uk": LIVE_MODE if settings.football_data_uk_enabled else FIXTURE_MODE,
        "crocobet": FIXTURE_MODE,
    }
    return summary


__all__ = [
    "AutomationScope",
    "adapter_mode_summary",
    "available_sources",
    "build_adapter",
    "build_fixture_adapters",
]
