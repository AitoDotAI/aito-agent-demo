"""Central knobs for the telco tool-routing benchmark.

Everything tunable lives here so a run is fully described by this file + the
seeds. Thresholds that must be *chosen on VAL* (gate, assist_floor, retrieval-k)
have defaults here but the runner overwrites them from results/chosen_params.json
after the VAL sweep — they are never set from TEST.

Fail loud on missing credentials: a benchmark that silently runs against the
wrong backend is worse than one that won't start.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# --- paths -----------------------------------------------------------------
PKG_ROOT = Path(__file__).resolve().parent.parent      # telco-tool-routing-bench/
REPO_ROOT = PKG_ROOT.parent                            # aito-agent-demo/
DATA_DIR = PKG_ROOT / "data"
RESULTS_DIR = PKG_ROOT / "results"
CALLS_LOG = RESULTS_DIR / "calls.jsonl"
CHOSEN_PARAMS = RESULTS_DIR / "chosen_params.json"


# --- env loading (shares the parent demo's .env) ---------------------------
def _load_dotenv() -> None:
    """Load REPO_ROOT/.env. Uses python-dotenv if present, else a minimal parser
    so config import never hard-depends on the package being installed yet."""
    # .env is authoritative for the benchmark: the dev shell (shell.nix) exports
    # a localhost default + empty key that would otherwise shadow real creds, so
    # we override ambient env from the file rather than deferring to it.
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
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ[k.strip()] = v.strip().strip('"').strip("'")


_load_dotenv()


def _require(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        raise RuntimeError(
            f"Missing required env var {name}. Copy .env.example into the repo-root "
            f".env and fill it in."
        )
    return v


# --- determinism -----------------------------------------------------------
SEED = 0x5151                      # one root seed; everything derives from it
TICKET_SEED = SEED ^ 0x71C9        # ticket generation
SPLIT_SEED = SEED ^ 0x5917         # train/val/test partition
TOOLS_SEED = SEED ^ 0x7001         # distractor tool padding


# --- dataset shape ---------------------------------------------------------
N_TICKETS = 300                    # spec minimum; point estimates, no CIs
# stratified difficulty mix (must sum to 1.0; asserted in tickets.py)
DIFFICULTY_MIX = {"clear": 0.45, "medium": 0.35, "ambiguous": 0.20}
SPLIT_RATIOS = {"train": 0.60, "val": 0.15, "test": 0.25}
ESCALATION_DESKS = ["Network Ops", "Billing", "Retention", "Tech Support", "Sales"]


# --- tool catalog sweep ----------------------------------------------------
TOOL_COUNTS = [12, 40, 120, 340]   # the sweep; LLM baselines see all N, Aito does not


# --- Aito ------------------------------------------------------------------
AITO_TABLE = "tickets"
PREDICT_LIMIT = 4                  # top-k candidates returned by _predict


# --- thresholds (DEFAULTS — overwritten from VAL via chosen_params.json) ----
# These exist so the modules import and a smoke run works; the runner replaces
# them with values chosen on VAL before touching TEST.
DEFAULT_GATE = 0.90                # >= gate  -> auto-fire, no LLM
DEFAULT_ASSIST_FLOOR = 0.60        # [floor, gate) -> LLM picks from top-4
DEFAULT_RETRIEVAL_K = 8            # Baseline B shortlist size


# --- embeddings (Baseline B) -----------------------------------------------
EMBED_MODEL = "all-MiniLM-L6-v2"   # local sentence-transformer, no API


# --- LLM (Azure OpenAI) ----------------------------------------------------
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


# --- pricing (for cost_usd) ------------------------------------------------
# Token COUNTS are measured from the API usage object; only this $/token
# conversion is a constant. These are the published OpenAI gpt-5-mini list
# rates (USD per 1M tokens). VERIFY against the Azure price sheet for the
# Sweden Central deployment before quoting cost figures externally — Azure
# regional pricing can differ. The rate actually used is printed into REPORT.md
# so the cost number is always traceable to a number you can check.
PRICE_INPUT_USD_PER_MTOK = 0.25
PRICE_OUTPUT_USD_PER_MTOK = 2.00   # includes reasoning tokens (billed as output)


def cost_usd(input_tokens: int, output_tokens: int) -> float:
    return (
        input_tokens / 1_000_000 * PRICE_INPUT_USD_PER_MTOK
        + output_tokens / 1_000_000 * PRICE_OUTPUT_USD_PER_MTOK
    )


# --- Aito creds (read at call sites, not import) ---------------------------
def aito_url() -> str:
    return _require("AITO_API_URL").rstrip("/")


def aito_read_key() -> str:
    return _require("AITO_API_KEY")


def aito_write_key() -> str:
    """RW key for uploads. Falls back to the read key (works only if that key
    has write scope on the shared instance)."""
    return os.environ.get("AITO_RW_KEY") or _require("AITO_API_KEY")
