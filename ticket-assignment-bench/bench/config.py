"""Config for the ticket field-assignment benchmark (v2).

Models the real failure that inspired this: a resolution pipeline inferred
customer/agent from top-N *text-similar* tickets, but similar-sounding tickets
came from different customers/projects, so the structured fields got corrupted.

This benchmark makes that failure measurable and LLM-free (embeddings + Aito
`_predict` only), so it scales to thousands of tickets in minutes.
"""

from __future__ import annotations

import os
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = PKG_ROOT.parent                       # aito-agent-demo/
DATA_DIR = PKG_ROOT / "data"
RESULTS_DIR = PKG_ROOT / "results"


def _load_dotenv() -> None:
    env_path = REPO_ROOT / ".env"
    try:
        from dotenv import load_dotenv  # type: ignore
        load_dotenv(env_path, override=True)
        return
    except ModuleNotFoundError:
        pass
    if not env_path.exists():
        return
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


def aito_url() -> str:
    return _require("AITO_API_URL").rstrip("/")


def aito_read_key() -> str:
    return _require("AITO_API_KEY")


def aito_write_key() -> str:
    return os.environ.get("AITO_RW_KEY") or _require("AITO_API_KEY")


# --- determinism ---
SEED = 0xA551
TEXT_SEED = SEED ^ 0x7E47
SAMPLE_SEED = SEED ^ 0x5A11

# --- Aito ---
AITO_TABLE = "assignments"
PREDICT_LIMIT = 5

# --- embeddings (shared with v1's local model) ---
EMBED_MODEL = "all-MiniLM-L6-v2"

# --- dataset ---
# A large labelled POOL is generated once; the scaling sweep takes nested TRAIN
# prefixes of increasing size and evaluates on a fixed held-out TEST split.
POOL_SIZE = 7000
TEST_SIZE = 800
TRAIN_SIZES = [250, 500, 1000, 2000, 4000]   # the data-scaling sweep
RETRIEVAL_K = 7                               # neighbours for the top-N baselines
GATE = 0.80                                   # Aito auto-assign confidence gate (set on VAL below)
