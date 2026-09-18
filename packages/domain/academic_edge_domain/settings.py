"""12-factor configuration shared by the API, worker and scripts."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from academic_edge_domain.enums import Role


class Settings(BaseSettings):
    """Runtime configuration.

    Values come from the process environment (and ``.env`` for local dev).
    Nothing is hard-coded to a provider secret: an empty key always falls back
    to the labelled-fixture path so the demo is reproducible without accounts.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- runtime ----
    academic_edge_env: str = Field(default="local")
    log_level: str = Field(default="INFO")
    database_url: str = Field(default="sqlite+pysqlite:///./.data/academic_edge.db")
    redis_url: str = Field(default="redis://localhost:6379/0")

    # ---- API ----
    api_host: str = Field(default="127.0.0.1")
    api_port: int = Field(default=8000)
    api_keys: str = Field(default="", description="CSV of `key:role` pairs")

    # ---- raw archive ----
    raw_archive_backend: str = Field(default="filesystem")
    raw_archive_dir: Path = Field(default=Path("./.data/raw-archive"))
    s3_endpoint_url: str = Field(default="")
    s3_bucket: str = Field(default="academic-edge-raw")

    # ---- providers ----
    api_football_key: str = Field(default="")
    api_football_base_url: str = Field(default="https://v3.football.api-sports.io")
    api_football_daily_quota: int = Field(default=100)

    football_data_org_token: str = Field(default="")
    football_data_org_base_url: str = Field(default="https://api.football-data.org/v4")
    football_data_org_rate_limit_per_min: int = Field(default=10)

    polymarket_gamma_base_url: str = Field(default="https://gamma-api.polymarket.com")
    polymarket_clob_base_url: str = Field(default="https://clob.polymarket.com")
    polymarket_ws_url: str = Field(default="wss://ws-subscriptions-clob.polymarket.com/ws/market")
    polymarket_enabled: bool = Field(default=True)

    football_data_uk_base_url: str = Field(default="https://www.football-data.co.uk")
    football_data_uk_enabled: bool = Field(default=True)

    crocobet_web_enabled: bool = Field(default=False)
    crocobet_csv_dir: Path = Field(default=Path("./.data/crocobet-inbox"))
    crocobet_terms_review_id: str = Field(default="")

    # ---- resolver ----
    resolver_auto_accept_threshold: float = Field(default=0.985)
    resolver_review_threshold: float = Field(default=0.940)
    resolver_time_window_minutes: int = Field(default=180)

    # ---- pricing ----
    pricing_max_quote_age_seconds: int = Field(default=180)
    pricing_slippage_bps: int = Field(default=15)
    pricing_exchange_fee_bps: int = Field(default=200)
    pricing_fx_spread_bps: int = Field(default=25)
    pricing_min_net_edge_bps: int = Field(default=50)
    pricing_quote_age_haircut_bps_per_min: int = Field(default=20)
    pricing_max_quote_age_haircut_bps: int = Field(default=200)
    pricing_bankroll: float = Field(default=1000.0)
    pricing_min_stake: float = Field(default=1.0)

    # ---- ml ----
    model_time_decay_half_life_days: int = Field(default=180)
    walk_forward_min_train_events: int = Field(default=200)
    mlflow_tracking_uri: str = Field(default="")

    @field_validator("log_level")
    @classmethod
    def _upper_log_level(cls, value: str) -> str:
        allowed = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
        upper = value.upper()
        if upper not in allowed:
            raise ValueError(f"LOG_LEVEL must be one of {sorted(allowed)}")
        return upper

    @field_validator("raw_archive_backend")
    @classmethod
    def _known_archive_backend(cls, value: str) -> str:
        allowed = {"filesystem", "s3"}
        if value not in allowed:
            raise ValueError(f"RAW_ARCHIVE_BACKEND must be one of {sorted(allowed)}")
        return value

    @field_validator("crocobet_web_enabled")
    @classmethod
    def _forbid_automation_in_this_build(cls, value: bool) -> bool:
        """Hard safety gate: this build refuses to switch Crocobet web ON.

        The policy layer raises ``PolicyViolation`` too; failing fast at config
        load means a misconfigured deployment cannot even start.
        """
        if value:
            raise ValueError(
                "CROCOBET_WEB_ENABLED=true is refused by this build. Crocobet is "
                "manual-CSV only until a recorded terms/permission review exists "
                "(see config/source_policies.yaml and docs/sources-and-terms.md)."
            )
        return value

    @property
    def is_local(self) -> bool:
        return self.academic_edge_env in {"local", "test"}

    @property
    def role_keys(self) -> dict[str, Role]:
        """Parse ``API_KEYS`` into ``{key: Role}``. Empty => dev-mode auth."""
        mapping: dict[str, Role] = {}
        for chunk in self.api_keys.split(","):
            item = chunk.strip()
            if not item:
                continue
            key, _, role = item.partition(":")
            if not key or not role:
                raise ValueError(f"invalid API_KEYS entry {item!r}; expected 'key:role'")
            mapping[key.strip()] = Role(role.strip().lower())
        return mapping

    @property
    def fixture_only(self) -> bool:
        """True when no live provider credentials exist -> demo from fixtures."""
        return not self.api_football_key and not self.football_data_org_token

    def resolve_db_url(self) -> str:
        """Resolve a relative SQLite path against the process CWD, creating dirs."""
        url = self.database_url
        if url.startswith("sqlite"):
            prefix, _, tail = url.partition("///")
            path = Path(tail)
            if not path.is_absolute():
                path = Path.cwd() / path
            path.parent.mkdir(parents=True, exist_ok=True)
            return f"{prefix}///{path.as_posix()}"
        return url


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings singleton (cheap to read, stable for a run)."""
    return Settings()


def reset_settings_cache() -> None:
    """Test hook: force re-read of environment variables."""
    get_settings.cache_clear()
