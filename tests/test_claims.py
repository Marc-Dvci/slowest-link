"""The README's headline numbers, recomputed from the committed plan and evidence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from slowest_link import checks, scoring
from slowest_link.cli import outcomes_for
from slowest_link.store import open_store

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.integration


def test_the_three_views_find_0_5_and_3_broken_promises() -> None:
    with open_store(ROOT / "plan", read_only=True) as conn:
        counts = {view: len(checks.inversions(conn, view)) for view in checks.VIEWS}
        chains = {view: len(checks.restore_chains(conn, view)) for view in checks.VIEWS}
    assert counts == {"plan": 0, "architecture": 5, "evidence": 3}
    assert chains == {"plan": 0, "architecture": 5, "evidence": 4}


def test_view_cart_breaks_its_promise_only_through_its_restore_chain() -> None:
    with open_store(ROOT / "plan", read_only=True) as conn:
        assert "View cart" not in {f.function for f in checks.inversions(conn, "evidence")}
        chain = {f.function: f for f in checks.restore_chains(conn, "evidence")}["View cart"]
    assert (chain.promise_min, chain.value_min) == (60, 90)


def test_every_observed_call_is_in_the_published_architecture_and_10_declared_calls_are_unseen() -> None:
    observed = json.loads((ROOT / "evidence" / "e0-observed-calls.json").read_text(encoding="utf-8"))
    assert (observed["traces"], observed["attributed"], len(observed["calls"])) == (1037, 1037, 24)
    with open_store(ROOT / "plan", read_only=True) as conn:
        assert checks.hidden_calls(conn) == []
        assert len(checks.unseen_calls(conn)) == 10


def test_the_stop_tests_score_as_the_readme_says() -> None:
    predictions = json.loads((ROOT / "evidence" / "predictions.json").read_text(encoding="utf-8"))
    by_test = {f["id"]: f["predicted"] for f in predictions["faults"]}
    with open_store(ROOT / "plan", read_only=True) as conn:
        outcomes, functions = outcomes_for(conn, ROOT / "evidence" / "e1e2")
    stops = [o for o in outcomes if o.kind == "stop"]
    got = {
        view: scoring.score(stops, {o.test: by_test[o.test][view] for o in stops}, functions).to_dict()
        for view in checks.VIEWS
    }
    assert (got["evidence"]["tp"], got["evidence"]["tp"] + got["evidence"]["fn"], got["evidence"]["fp"]) == (39, 40, 4)
    assert (got["architecture"]["tp"], got["architecture"]["fp"]) == (40, 91)
    assert (got["plan"]["tp"], got["plan"]["fp"]) == (25, 3)
    assert got["evidence"]["exact"] == 15 and len(stops) == 20


def test_the_predictions_name_the_vault_commit_they_came_from_and_cover_every_test() -> None:
    predictions = json.loads((ROOT / "evidence" / "predictions.json").read_text(encoding="utf-8"))
    tests = [
        json.loads(line)["test"]
        for line in (ROOT / "evidence" / "e1e2" / "timeline.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert predictions["vault_commit"] == "8211f9f"
    assert sorted(tests) == sorted(f["id"] for f in predictions["faults"])


def test_the_tests_wrote_one_needed_call_and_two_survivable_calls_into_the_plan() -> None:
    with open_store(ROOT / "plan", read_only=True) as conn:
        needed = [
            dict(r)
            for r in conn.execute(
                "MATCH (a)-[r:CALLS]->(b) WHERE size(coalesce(r.needed_by, [])) > 0 RETURN a.name AS a, b.name AS b, r.needed_by AS f"
            )
        ]
        survived = [
            dict(r)
            for r in conn.execute(
                "MATCH (a)-[r:CALLS]->(b) WHERE size(coalesce(r.survives_without, [])) > 0 RETURN a.name AS a, b.name AS b ORDER BY a"
            )
        ]
    assert needed == [{"a": "checkout", "b": "kafka", "f": ["Place an order"]}]
    assert [(s["a"], s["b"]) for s in survived] == [("checkout", "email"), ("fraud-detection", "flagd")]


def test_the_recorded_agent_answers_grade_as_the_readme_says() -> None:
    import sys

    sys.path.insert(0, str(ROOT / "experiments"))
    import agent_eval

    questions = json.loads((ROOT / "evidence" / "agent-eval" / "questions.json").read_text(encoding="utf-8"))
    runs = [
        json.loads(line)
        for line in (ROOT / "evidence" / "agent-eval" / "runs.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    summary = agent_eval.grade(questions, runs)
    assert (summary["files"]["correct"], summary["files"]["answers"]) == (36, 36)
    assert (summary["tools"]["correct"], summary["tools"]["answers"]) == (31, 36)
    assert summary == json.loads((ROOT / "evidence" / "agent-eval" / "summary.json").read_text(encoding="utf-8"))
