"""Sales numbers a buyer can believe (CRO, 2026-10-01): B2B deals win around 15-40% of the
time and a good cold outreach books a meeting a few percent of the time. The fixture draws
from believable rates, and every win probability is shown against the counted base rate."""

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import seed_sales as S  # noqa: E402

from src import app as A  # noqa: E402


def test_the_fixture_draws_believable_rates():
    rng = random.Random(S.SEED)
    eng, out = S.build_engagements(rng), S.build_outreach(rng)
    win = sum(e["outcome"] == "won" for e in eng) / len(eng)
    meet = sum(o["meeting"] == "yes" for o in out) / len(out)
    assert 0.15 <= win <= 0.30, win
    assert 0.02 <= meet <= 0.06, meet
    strong = [e for e in eng if e["lead_source"] == "Referral" and e["competitive"] == "Sole-source"]
    rate = sum(e["outcome"] == "won" for e in strong) / len(strong)
    assert 0.35 <= rate <= 0.65, rate            # a strong deal is likely, not certain


def test_seeding_is_a_dry_run_unless_applied(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["seed_sales.py"])
    monkeypatch.setattr(S, "_upload", lambda *a, **k: (_ for _ in ()).throw(AssertionError("wrote without --apply")))
    S.main()
    assert "dry run" in capsys.readouterr().out


class _Eng:
    def query(self, table, where=None, select=None, order_by=None, limit=5):
        return {"hits": [], "total": 200 if (where or {}).get("outcome") == "won" else 1000}

    def predict(self, table, where, target, limit=5, select=None):
        return {"hits": [{"feature": "won", "$p": 0.5}, {"feature": "lost", "$p": 0.5}]}


def test_win_odds_come_with_the_counted_base_rate(monkeypatch):
    monkeypatch.setattr(A, "aito", _Eng())
    monkeypatch.setitem(A._BASE_WIN_CACHE, "at", 0.0)
    r = A._tool_win_odds({"industry": "SaaS"})
    assert (r["win_probability"], r["base_win_rate"], r["times_the_base"]) == (0.5, 0.2, 2.5)


def test_the_reseed_keeps_the_live_tables_engine_and_types():
    """Rows change; the table's own schema (its engine included) is what gets recreated."""
    live = {"type": "table", "engine": "v2", "columns": {c: {"type": "String"} for c in ("a", "b")}}
    sent = {}

    class _H:
        def get(self, path):
            body = {"schema": {"t": live}} if path == "/schema" else sent.get("schema", {})
            return type("R", (), {"json": lambda self: body, "status_code": 200})()

        def delete(self, path):
            return type("R", (), {"status_code": 200})()

        def put(self, path, json):
            sent["schema"] = json
            return type("R", (), {"status_code": 200})()

        def post(self, path, json):
            return type("R", (), {"status_code": 200, "json": lambda self: {"total": 2}, "text": ""})()

    S._upload(_H(), "t", {"type": "table", "columns": {"a": {}, "b": {}}}, [{}, {}])
    assert sent["schema"] is live                                  # the live schema, engine and all
