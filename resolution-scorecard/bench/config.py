"""Config for the resolution scorecard.

One dataset, several resolution paths. Each ticket carries its resolved
{intent, + the one parameter that intent needs}. Aito predicts each field
directly from {text, sender_domain}; an LLM agent does the same in a structured
call. We score better (accuracy) / faster (latency) / cheaper ($ per 1000).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = PKG_ROOT.parent
DATA_DIR = PKG_ROOT / "data"
RESULTS_DIR = PKG_ROOT / "results"
CALLS_LOG = RESULTS_DIR / "calls.jsonl"


def _load_dotenv() -> None:
    env_path = REPO_ROOT / ".env"
    try:
        from dotenv import load_dotenv  # type: ignore
        load_dotenv(env_path, override=True)
        return
    except ModuleNotFoundError:
        pass
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip().strip('"').strip("'")


_load_dotenv()


def _require(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        raise RuntimeError(f"Missing env var {name}; fill the repo-root .env")
    return v


def aito_url() -> str: return _require("AITO_API_URL").rstrip("/")
def aito_read_key() -> str: return _require("AITO_API_KEY")
def aito_write_key() -> str: return os.environ.get("AITO_RW_KEY") or _require("AITO_API_KEY")


@dataclass(frozen=True)
class LLMConfig:
    endpoint: str
    api_key: str
    deployment: str
    model_name: str
    api_version: str


def load_llm_config() -> LLMConfig:
    return LLMConfig(
        endpoint=_require("OPENAI_MODEL_URL").rstrip("/"),
        api_key=_require("OPENAI_MODEL_API_KEY"),
        deployment=_require("OPENAI_MODEL_DEPLOYMENT"),
        model_name=os.environ.get("OPENAI_MODEL_NAME", "gpt-5-mini"),
        api_version=os.environ.get("OPENAI_MODEL_API_VERSION", "2024-08-01-preview"),
    )


# gpt-5-mini published list rates (USD / 1M tokens). The rate used is printed
# into the report so the cost figure is traceable.
PRICE_INPUT_USD_PER_MTOK = 0.25
PRICE_OUTPUT_USD_PER_MTOK = 2.00


def cost_usd(in_tok: int, out_tok: int) -> float:
    return in_tok / 1_000_000 * PRICE_INPUT_USD_PER_MTOK + out_tok / 1_000_000 * PRICE_OUTPUT_USD_PER_MTOK


# --- determinism / dataset ---
SEED = 0x5C04
AITO_TABLE = "resolutions"
PREDICT_LIMIT = 4
TRAIN_SIZE = 4000
TEST_SIZE = 800
LLM_SAMPLE = 80                 # tickets the real LLM agent is measured on
GATE = 0.80                     # confidence to auto-resolve a field

# Measured Aito round-trip per _predict (ms) is timed live; this is only a
# documented reference from earlier runs.
AITO_REF_MS = 90

# --- the resolution paths ---
# intent -> the single parameter field that intent must fill (or None)
INTENT_PARAM = {
    "cancel_service": "target_service",
    "refund": "target_service",
    "check_outage": "location",
    "find_shop": "location",
    "repair_help": "kb_article",
    "check_balance": None,
}
INTENTS = list(INTENT_PARAM)
PARAM_FIELDS = ["target_service", "location", "kb_article"]

SERVICES = ["broadband", "mobile_plan", "tv_package", "landline", "roaming_addon", "cloud_storage"]
CITIES = ["Helsinki", "Espoo", "Tampere", "Turku", "Oulu", "Vantaa", "Jyvaskyla", "Lahti"]
KB_ARTICLES = ["cracked_screen", "battery_drain", "water_damage", "wont_charge", "no_signal", "software_update"]
