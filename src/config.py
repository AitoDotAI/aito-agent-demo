"""Env loading for the demo backend. Fail loud on missing required values
so deployment misconfiguration surfaces at startup, not on the first request.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import dotenv_values, find_dotenv


def _load_dotenv() -> None:
    """Fill the environment from .env without overriding it.

    In production the platform sets env vars directly via App Service
    settings and there is no .env, so this is a no-op. In local dev a
    variable the caller set wins over the file, so
    `AITO_API_URL=http://localhost:8080 AITO_API_VERSION=v2 ./do ...` really
    targets that engine and API. This used `load_dotenv(override=True)`,
    where the file won: on 2026-09-20 a loader run pointed at localhost
    silently wrote to the production instance (shared.aito.ai) instead.

    An empty variable counts as unset, so a blank export still picks up
    the file's value rather than shadowing it.
    """
    for key, value in dotenv_values(find_dotenv()).items():
        if value is not None and not os.environ.get(key):
            os.environ[key] = value


_load_dotenv()


@dataclass(frozen=True)
class Config:
    aito_url: str          # db root, already including /env/<name> when aito_env is set
    aito_key: str
    aito_api_version: str  # "v1" | "v2" — which REST surface AitoClient targets
    aito_env: str | None   # Aito environment (copy-on-write branch); None = env.master


def load_config() -> Config:
    url = os.environ.get("AITO_API_URL")
    key = os.environ.get("AITO_API_KEY")
    if not url or not key:
        raise ValueError(
            "No Aito credentials found. Set AITO_API_URL + AITO_API_KEY in .env "
            "(copy from .env.example to get started)."
        )
    # Both default to today's production behaviour: v1 against env.master. The v2
    # migration is opt-in per-environment so prod is unaffected until we cut over.
    version = os.environ.get("AITO_API_VERSION", "v1").strip().lower()
    if version not in ("v1", "v2"):
        raise ValueError(f"AITO_API_VERSION must be 'v1' or 'v2', got {version!r}")

    # An Aito environment is selected purely by URL path — never by a body field,
    # query param or header — so it is folded into the base URL here:
    #   https://host/db/<db>            → env.master
    #   https://host/db/<db>/env/<name> → that branch
    env = (os.environ.get("AITO_ENV") or "").strip() or None
    base = url.rstrip("/")
    if env and not base.endswith(f"/env/{env}"):
        base = f"{base}/env/{env}"

    return Config(aito_url=base, aito_key=key, aito_api_version=version, aito_env=env)
