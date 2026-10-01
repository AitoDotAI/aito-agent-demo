"""The held-out support queue was never LOADED into Aito, but 166 of its 300 tickets
repeat the wording of loaded ones (2026-09-30 sanity check). The copy says so, and the
benchmark carries the novel-wording re-score next to the published one."""

from pathlib import Path

from fastapi.testclient import TestClient

from src import app as A

ROOT = Path(__file__).resolve().parents[1]


def test_the_benchmark_serves_the_novel_wording_rescore():
    b = TestClient(A.app).get("/api/support/benchmark").json()
    novel = b["novel_text"]["groups"]["novel_text"]
    assert novel["n"] == 134 and novel["arms"]["aito_only"]["all_five_right"] == 0.619


def test_no_copy_claims_aito_never_saw_the_tickets():
    files = [ROOT / "frontend/components/EnvelopeView.tsx", ROOT / "frontend/components/AppShell.tsx",
             ROOT / "frontend/components/SupportReply.tsx", ROOT / "scripts/support_fixture/README.md"]
    for f in files:
        text = f.read_text().lower()
        for claim in ("never seen", "never saw", "has not seen"):
            assert claim not in text, f"{f.name}: '{claim}'"
