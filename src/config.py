"""Env loading for the demo backend. Fail loud on missing required values
so deployment misconfiguration surfaces at startup, not on the first request.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

# In production the platform sets env vars directly via App Service settings;
# python-dotenv finds no .env and is a no-op. In local dev it loads ./.env —
# with override=True so a real .env wins over shell defaults (e.g. shell.nix
# exports an empty AITO_API_KEY that would otherwise shadow the .env value).
# Keep .env's credential precedence, but allow explicit migration targets to
# select the API and branch in `AITO_API_VERSION=v2 AITO_ENV=v2 ./do ...`.
_target_overrides = {k: os.environ[k] for k in ("AITO_API_VERSION", "AITO_ENV") if k in os.environ}
load_dotenv(override=True)
os.environ.update(_target_overrides)


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
