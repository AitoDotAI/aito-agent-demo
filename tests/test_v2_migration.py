"""Regression tests for migration checks that previously gave false assurance."""

import json
import os
import subprocess
import sys

from scripts.v2_check import route_errors
from scripts.v2_parity import ROUTES
from scripts.v2_relate_check import check_rates


def test_scoped_statistics_must_follow_labels_not_transposed_cells():
    # Invented contingency table: 100 cases, 60 outcomes, 25 with the driver,
    # 20 both. Reversed probabilities remain plausible and within [0,1].
    counts = dict(population=100, outcome=60, driver=25, both=20)
    reversed_hit = {
        "fs": {"n": 100, "f": 25, "fCondition": 60,
               "fOnCondition": 20, "fOnNotCondition": 5},
        "ps": {"p": 0.25, "pCondition": 0.6,
               "pOnCondition": 20/60, "pOnNotCondition": 5/40},
    }
    assert any("ps.pOnCondition" in e for e in check_rates(reversed_hit, **counts))
    correct_hit = {
        "fs": {"n": 100, "f": 60, "fCondition": 25,
               "fOnCondition": 20, "fOnNotCondition": 40},
        "ps": {"p": 0.6, "pCondition": 0.25,
               "pOnCondition": 0.8, "pOnNotCondition": 40/75},
    }
    assert check_rates(correct_hit, **counts) == []


def test_http_success_is_not_enough_for_golden_intent():
    path = "/api/resolve?text=my+broadband+keeps+dropping+every+evening"
    body = {"intent": "cancel_service", "intent_p": 0.96,
            "intent_alts": [{"value": "cancel_service", "confidence": 0.96}]}
    assert route_errors(path, 200, body)
    body["intent"] = "repair_help"
    body["intent_alts"][0]["value"] = "repair_help"
    assert route_errors(path, 200, body) == []
    assert route_errors(path, 502, {})


def test_parity_does_not_call_paid_llm_route():
    assert not any(path.split("?")[0] == "/api/route" for path in ROUTES)


def test_explicit_migration_target_wins_over_dotenv():
    # Simulate a .env pinning v1/master without touching the developer's file.
    code = """
import os, dotenv, json
def dotenv_with_pinned_target(**kwargs):
    os.environ.update(AITO_API_VERSION='v1', AITO_ENV='',
                      AITO_API_URL='https://example.invalid/db/demo', AITO_API_KEY='test')
dotenv.load_dotenv = dotenv_with_pinned_target
from src.config import load_config
c = load_config()
print(json.dumps([c.aito_api_version, c.aito_env, c.aito_url]))
"""
    result = subprocess.run([sys.executable, "-c", code], check=True,
                            env=dict(os.environ, AITO_API_VERSION="v2", AITO_ENV="v2"),
                            capture_output=True, text=True)
    assert json.loads(result.stdout) == ["v2", "v2", "https://example.invalid/db/demo/env/v2"]
