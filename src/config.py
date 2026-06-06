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
load_dotenv(override=True)


@dataclass(frozen=True)
class Config:
    aito_url: str
    aito_key: str


def load_config() -> Config:
    url = os.environ.get("AITO_API_URL")
    key = os.environ.get("AITO_API_KEY")
    if not url or not key:
        raise ValueError(
            "No Aito credentials found. Set AITO_API_URL + AITO_API_KEY in .env "
            "(copy from .env.example to get started)."
        )
    return Config(aito_url=url.rstrip("/"), aito_key=key)
