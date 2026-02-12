from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any, Optional

import yaml

from backtest_system.core.exceptions import ConfigurationError


def _as_bool(value: object, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    s = str(value).strip().lower()
    if s in {"1", "true", "yes", "y", "on"}:
        return True
    if s in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _get(d: dict, path: str, default: Any = None) -> Any:
    cur: Any = d
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


@dataclass(frozen=True)
class ApiConfig:
    read_url: str
    write_url: str
    token: str
    timeout_seconds: int = 30
    # Whether to trust process env (HTTP(S)_PROXY/NO_PROXY, REQUESTS_CA_BUNDLE, etc.).
    # Default to False to avoid surprising proxy issues with internal IPs (e.g. 100.64/10).
    trust_env: bool = False


@dataclass(frozen=True)
class DatabaseConfig:
    url: Optional[str] = None


@dataclass(frozen=True)
class AppConfig:
    output_dir: str = "output"
    non_interactive: bool = True
    on_escalate: str = "halt"  # halt | retry | skip


@dataclass(frozen=True)
class BacktestConfig:
    database: DatabaseConfig
    api: ApiConfig
    app: AppConfig


def load_config(path: str | None = None) -> BacktestConfig:
    """
    Load configuration from an optional YAML file, then override with env vars.

    Env vars (highest priority):
      - BACKTEST_DB_URL
      - BACKTEST_API_READ_URL
      - BACKTEST_API_WRITE_URL
      - BACKTEST_API_TOKEN
      - BACKTEST_API_TIMEOUT_SECONDS
      - BACKTEST_API_TRUST_ENV
      - BACKTEST_OUTPUT_DIR
      - BACKTEST_NON_INTERACTIVE
      - BACKTEST_ON_ESCALATE   (halt|retry|skip)
    """
    file_cfg: dict[str, Any] = {}
    if path:
        p = Path(path)
        if not p.exists():
            raise ConfigurationError(f"Config file not found: {path}")
        file_cfg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        if not isinstance(file_cfg, dict):
            raise ConfigurationError("Config file root must be a YAML mapping/object")

    # Defaults (safe/no-secrets).
    db_url = _get(file_cfg, "database.url", None)
    api_read_url = _get(file_cfg, "api.read_url", "http://localhost:8000")
    api_write_url = _get(file_cfg, "api.write_url", "http://localhost:8000")
    api_token = _get(file_cfg, "api.token", "")
    api_timeout = int(_get(file_cfg, "api.timeout_seconds", 30) or 30)
    api_trust_env = _as_bool(_get(file_cfg, "api.trust_env", False), default=False)
    output_dir = _get(file_cfg, "app.output_dir", "output")
    non_interactive = _as_bool(_get(file_cfg, "app.non_interactive", True), default=True)
    on_escalate = str(_get(file_cfg, "app.on_escalate", "halt") or "halt").strip().lower()

    # Env overrides.
    db_url = os.getenv("BACKTEST_DB_URL", db_url or None)
    api_read_url = os.getenv("BACKTEST_API_READ_URL", api_read_url)
    api_write_url = os.getenv("BACKTEST_API_WRITE_URL", api_write_url)
    api_token = os.getenv("BACKTEST_API_TOKEN", api_token)
    api_timeout = int(os.getenv("BACKTEST_API_TIMEOUT_SECONDS", str(api_timeout)))
    api_trust_env = _as_bool(os.getenv("BACKTEST_API_TRUST_ENV", api_trust_env), default=False)
    output_dir = os.getenv("BACKTEST_OUTPUT_DIR", output_dir)
    non_interactive = _as_bool(os.getenv("BACKTEST_NON_INTERACTIVE", non_interactive), default=True)
    on_escalate = os.getenv("BACKTEST_ON_ESCALATE", on_escalate).strip().lower()

    if on_escalate not in {"halt", "retry", "skip"}:
        raise ConfigurationError("BACKTEST_ON_ESCALATE must be one of: halt, retry, skip")

    return BacktestConfig(
        database=DatabaseConfig(url=db_url),
        api=ApiConfig(
            read_url=api_read_url.rstrip("/"),
            write_url=api_write_url.rstrip("/"),
            token=api_token,
            timeout_seconds=api_timeout,
            trust_env=api_trust_env,
        ),
        app=AppConfig(
            output_dir=output_dir,
            non_interactive=non_interactive,
            on_escalate=on_escalate,
        ),
    )
