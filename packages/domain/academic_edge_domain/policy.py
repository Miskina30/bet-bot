"""Source policy registry -- code-level enforcement of the brief's safety rules.

The YAML registry (``config/source_policies.yaml``) is the single source of truth
for *what we are allowed to automate*. Two rules are enforced mechanically:

1. **No automation without a policy entry.** :meth:`SourcePolicyRegistry.require_live_client`
   raises :class:`PolicyViolation` for an unknown source, for a source whose
   ``automation_allowed`` is false, or for a scope that does not match (e.g.
   asking the Crocobet adapter for an HTTP client).
2. **No Crocobet web automation until a human records a review.** The registry
   refuses even when a caller passes ``approved=True`` unless ``terms_reviewed_by``
   AND ``terms_reviewed_at`` are set in the registry file -- so enabling it needs a
   committed, reviewable change.

Academic Edge is read-only: :func:`assert_read_only_intent` makes any future
contribution that tries to add order placement fail loudly.
"""

from __future__ import annotations

import datetime as dt
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from academic_edge_domain.enums import AutomationScope, SourceTier
from academic_edge_domain.models import AuditLog, SourcePolicyRecord
from academic_edge_domain.time import parse_timestamp, utcnow

POLICY_ENV_VAR = "ACADEMIC_EDGE_POLICY_FILE"
DEFAULT_POLICY_RELATIVE = Path("config") / "source_policies.yaml"


class PolicyViolation(RuntimeError):  # noqa: N818  (public API name, kept stable)
    """Raised when a requested action is outside the recorded source policy."""


class PolicyFileNotFound(PolicyViolation):
    """Raised when the registry file cannot be located."""


@dataclass(frozen=True, slots=True)
class SourcePolicy:
    """One reviewed provider entry."""

    source_id: str
    display_name: str
    tier: SourceTier
    license: str
    auth: str
    automation_allowed: bool
    automation_scope: AutomationScope
    rate_limit_per_minute: int = 0
    quota_notes: str | None = None
    vendor_url: str | None = None
    docs_url: str | None = None
    terms_reviewed_by: str | None = None
    terms_reviewed_at: dt.datetime | None = None
    enabled_by_default: bool = True
    data_classes: tuple[str, ...] = ()
    notes: str = ""

    @property
    def terms_reviewed(self) -> bool:
        """True only when a named human and a timestamp are both recorded."""
        return bool(self.terms_reviewed_by) and self.terms_reviewed_at is not None

    def describe(self) -> dict[str, Any]:
        """Compact, API-safe summary used by the dashboard."""
        return {
            "source_id": self.source_id,
            "display_name": self.display_name,
            "tier": str(self.tier),
            "automation_allowed": self.automation_allowed,
            "automation_scope": str(self.automation_scope),
            "terms_reviewed": self.terms_reviewed,
            "quota_notes": self.quota_notes,
        }


@dataclass(frozen=True, slots=True)
class SourcePolicyRegistry:
    """Loaded registry with lookup and guard helpers."""

    version: int
    policies: dict[str, SourcePolicy] = field(default_factory=dict)
    source_path: Path | None = None

    def __contains__(self, source_id: object) -> bool:
        return source_id in self.policies

    def get(self, source_id: str) -> SourcePolicy:
        try:
            return self.policies[source_id]
        except KeyError as exc:
            raise PolicyViolation(
                f"source {source_id!r} has no entry in the source policy registry. "
                "Add it to config/source_policies.yaml before writing an adapter."
            ) from exc

    def enabled_sources(self) -> list[SourcePolicy]:
        return [p for p in self.policies.values() if p.enabled_by_default]

    def require_live_client(self, source_id: str, scope: AutomationScope) -> SourcePolicy:
        """Gate for any code path that would touch a provider over the network."""
        policy = self.get(source_id)
        if not policy.automation_allowed:
            raise PolicyViolation(
                f"automation is disabled for source {source_id!r} "
                f"(scope={policy.automation_scope}). Use the manual/fixture path."
            )
        if policy.automation_scope != scope:
            raise PolicyViolation(
                f"source {source_id!r} permits scope {policy.automation_scope}, not {scope}."
            )
        if policy.automation_scope is AutomationScope.MANUAL_CSV_ONLY and not policy.terms_reviewed:
            raise PolicyViolation(
                f"source {source_id!r} is manual-CSV only and its terms review is not "
                "recorded; refusing to build a network client."
            )
        return policy

    def require_manual_import(self, source_id: str) -> SourcePolicy:
        """Gate for operator-supplied CSV imports (the only Crocobet path)."""
        policy = self.get(source_id)
        if policy.automation_scope is not AutomationScope.MANUAL_CSV_ONLY:
            raise PolicyViolation(
                f"source {source_id!r} is not a manual-CSV source "
                f"(scope={policy.automation_scope})."
            )
        return policy

    def require_recorded_review(self, source_id: str) -> SourcePolicy:
        """Assert that a human review exists (used by the web-automation gate)."""
        policy = self.get(source_id)
        if not policy.terms_reviewed:
            raise PolicyViolation(
                f"source {source_id!r} has no recorded terms review "
                "(terms_reviewed_by/terms_reviewed_at are null)."
            )
        return policy


def repo_root(start: Path | None = None) -> Path:
    """Walk up from ``start`` until a directory containing pyproject.toml is found."""
    current = (start or Path(__file__).resolve()).resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "pyproject.toml").is_file():
            return candidate
    return Path.cwd()


def resolve_policy_path(explicit: Path | None = None) -> Path:
    """Locate the registry: explicit arg > env var > repository root > CWD."""
    if explicit is not None:
        if not explicit.is_file():
            raise PolicyFileNotFound(f"policy file not found: {explicit}")
        return explicit

    env_value = os.environ.get(POLICY_ENV_VAR)
    if env_value:
        env_path = Path(env_value)
        if not env_path.is_file():
            raise PolicyFileNotFound(f"{POLICY_ENV_VAR} points at a missing file: {env_path}")
        return env_path

    for base in (repo_root(), Path.cwd()):
        candidate = base / DEFAULT_POLICY_RELATIVE
        if candidate.is_file():
            return candidate
    raise PolicyFileNotFound(
        f"could not find config/source_policies.yaml; set {POLICY_ENV_VAR} to an absolute path."
    )


def load_registry(path: Path | None = None) -> SourcePolicyRegistry:
    """Parse the YAML registry into immutable policies."""
    policy_path = resolve_policy_path(path)
    raw = yaml.safe_load(policy_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict) or "sources" not in raw:
        raise PolicyViolation(f"{policy_path} is not a valid source policy registry")

    policies: dict[str, SourcePolicy] = {}
    for entry in raw["sources"]:
        if not isinstance(entry, dict) or "source_id" not in entry:
            raise PolicyViolation(f"{policy_path}: every source needs a source_id")
        reviewed_at = entry.get("terms_reviewed_at")
        policy = SourcePolicy(
            source_id=str(entry["source_id"]),
            display_name=str(entry.get("display_name", entry["source_id"])),
            tier=SourceTier(entry["tier"]),
            license=str(entry.get("license", "")),
            auth=str(entry.get("auth", "none")),
            automation_allowed=bool(entry.get("automation_allowed", False)),
            automation_scope=AutomationScope(entry["automation_scope"]),
            rate_limit_per_minute=int(entry.get("rate_limit_per_minute", 0)),
            quota_notes=entry.get("quota_notes"),
            vendor_url=entry.get("vendor_url"),
            docs_url=entry.get("docs_url"),
            terms_reviewed_by=entry.get("terms_reviewed_by"),
            terms_reviewed_at=parse_timestamp(reviewed_at) if reviewed_at else None,
            enabled_by_default=bool(entry.get("enabled_by_default", True)),
            data_classes=tuple(str(x) for x in entry.get("data_classes", ())),
            notes=str(entry.get("notes", "")).strip(),
        )
        if policy.source_id in policies:
            raise PolicyViolation(f"{policy_path}: duplicate source_id {policy.source_id!r}")
        policies[policy.source_id] = policy

    return SourcePolicyRegistry(
        version=int(raw.get("version", 1)), policies=policies, source_path=policy_path
    )


def sync_registry_to_db(
    session: Session, registry: SourcePolicyRegistry, *, actor: str = "system"
) -> int:
    """Upsert every policy into ``source_policy`` (idempotent; audited)."""
    now = utcnow()
    changed = 0
    for policy in registry.policies.values():
        row = session.scalars(
            select(SourcePolicyRecord).where(SourcePolicyRecord.source_id == policy.source_id)
        ).first()
        if row is None:
            row = SourcePolicyRecord(
                source_id=policy.source_id,
                display_name=policy.display_name,
                tier=policy.tier,
                license=policy.license,
                auth=policy.auth,
                automation_allowed=policy.automation_allowed,
                automation_scope=policy.automation_scope,
            )
            session.add(row)
        row.display_name = policy.display_name
        row.vendor_url = policy.vendor_url
        row.docs_url = policy.docs_url
        row.tier = policy.tier
        row.license = policy.license
        row.auth = policy.auth
        row.quota_notes = policy.quota_notes
        row.automation_allowed = policy.automation_allowed
        row.automation_scope = policy.automation_scope
        row.rate_limit_per_minute = policy.rate_limit_per_minute
        row.terms_reviewed_by = policy.terms_reviewed_by
        row.terms_reviewed_at = policy.terms_reviewed_at
        row.enabled = policy.enabled_by_default
        row.data_classes = list(policy.data_classes)
        row.notes = policy.notes
        row.registry_version = registry.version
        changed += 1

    session.add(
        AuditLog(
            action="policy_change",
            actor=actor,
            occurred_at=now,
            detail={"registry_version": registry.version, "sources": changed},
        )
    )
    session.flush()
    return changed


def assert_read_only_intent(operation: str) -> None:
    """Guard for future contributions: nothing here may place or sign anything."""
    forbidden = (
        "place_order",
        "place_bet",
        "submit_order",
        "sign_transaction",
        "withdraw",
        "deposit",
        "approve_token",
    )
    normalised = operation.strip().lower()
    if any(token in normalised for token in forbidden):
        raise PolicyViolation(
            f"operation {operation!r} is outside the read-only scope of Academic Edge. "
            "No wagering, no wallet signing, no bookmaker credentials."
        )
