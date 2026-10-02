"""Buyer-credibility fixes from the CRO's screenshot reshoot (2026-10-01):
the effort line's arithmetic must visibly add up, reference projects must read as distinct
past work (no templated em-dash lines), and a lever's KPI is an association, not a promise."""

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import seed_sales as S  # noqa: E402

from src import app as A  # noqa: E402

FRONT = Path(__file__).resolve().parents[1] / "frontend" / "components"


def test_reference_briefs_are_distinct_and_have_no_em_dash():
    eng = S.build_engagements(random.Random(S.SEED))
    assert not [r["brief"] for r in eng if "—" in r["brief"]]
    for (ind, svc) in {(r["client_industry"], r["service_line"]) for r in eng}:
        group = [r["brief"] for r in eng if (r["client_industry"], r["service_line"]) == (ind, svc)]
        assert len(set(group[:20])) == min(20, len(group)), (ind, svc)     # 20 distinct before any repeat


def test_the_cards_references_describe_different_work(monkeypatch):
    class _Q:
        def query(self, table, where=None, select=None, order_by=None, limit=5):
            same = "built demand forecasting that cut stock-outs."
            briefs = [f"A grocery chain: {same}", f"A fashion brand: {same}",
                      "A sports chain: built the pricing analytics behind its quarterly price review.",
                      "A pharmacy chain: automated invoice classification for the finance team."]
            return {"hits": [{"brief": b, "effort_days": 40, "deal_size_band": "M", "region": "Helsinki"} for b in briefs]}
    monkeypatch.setattr(A, "aito", _Q())
    refs = A._tool_find_references({"industry": "Retail", "service_line": "Analytics & ML"})["references"]
    works = [r["brief"].split(": ", 1)[1] for r in refs]
    assert len(refs) == 3 and len(set(works)) == 3


def test_effort_shows_the_exact_day_rate_and_the_360_no_causal_promise():
    sales = (FRONT / "SalesView.tsx").read_text()
    assert "eur(sheet.business_case.day_rate)" not in sales            # €1,100 rounded to "€1k"
    company = (FRONT / "CompanyDashboardView.tsx").read_text() + (FRONT / "CompanyAgentView.tsx").read_text()
    assert "pull the top lever" not in company and "pp better" not in company
    assert "if moved to" not in (Path(__file__).resolve().parents[1] / "src" / "company_agent.py").read_text()
