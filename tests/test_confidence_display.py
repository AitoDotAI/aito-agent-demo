"""Confidence on screen is the real $p, and one gate decides "sure" everywhere
(2026-09-30 sanity check, item e: ConfidenceBar capped every $p at 0.99, and the
Tool routing view used a 0.9 gate while the rest of the app uses 0.85)."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONT = ROOT / "frontend"


def test_one_gate_in_python_and_typescript():
    from src import gates
    from src import app as A
    from src import support_envelope as env
    assert (A._AUTO_GATE, A._ASSIST_GATE) == (env.AUTO, env.ASSIST) == (gates.AUTO_GATE, gates.ASSIST_GATE)
    ts = (FRONT / "lib" / "gates.ts").read_text()
    assert float(re.search(r"AUTO_GATE = ([0-9.]+)", ts).group(1)) == gates.AUTO_GATE
    assert float(re.search(r"ASSIST_GATE = ([0-9.]+)", ts).group(1)) == gates.ASSIST_GATE


def test_no_component_caps_or_hardcodes_a_confidence():
    for f in (FRONT / "components").rglob("*.tsx"):
        src = f.read_text()
        assert not re.search(r"Math\.min\(\s*\w+\s*,\s*0\.99\s*\)", src), f"{f.name}: caps $p at 0.99"
        assert not re.search(r"(?:top|p|value|conf)\s*>=\s*0\.\d+", src), f"{f.name}: a literal confidence gate"
