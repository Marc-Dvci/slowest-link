"""The scoring rules fixed in experiments/PROTOCOL.md, at and around each threshold."""

from __future__ import annotations

from typing import Any

import pytest

from slowest_link import scoring
from slowest_link.scoring import Window

TEST = {"test": "stop:x", "kind": "stop", "target": "x", "t_baseline": 0.0, "t_fault": 100.0, "t_fault_end": 200.0}
JOURNEYS = {"user_a": "Function A", "user_b": "Function B"}
BACKOFFICE = {"ledger": "Record orders", "fraud": "Screen orders"}


def attempts(journey: str, start: float, n: int, failures: int = 0, latency: float = 0.1) -> list[dict[str, Any]]:
    return [
        {"journey": journey, "t": start + i, "ok": i >= failures, "latency_s": latency} for i in range(n)
    ]


def test_p95_uses_the_nearest_rank() -> None:
    assert scoring.p95([float(i) for i in range(1, 21)]) == 19.0
    assert scoring.p95([5.0]) == 5.0
    assert scoring.p95([]) is None


def test_an_attempt_belongs_to_the_window_its_start_falls_in() -> None:
    records = [{"journey": "j", "t": t, "ok": True, "latency_s": 0.1} for t in (99.999, 100.0, 199.999, 200.0)]
    assert scoring.window(records, "j", 0, 100).attempts == 1
    assert scoring.window(records, "j", 100, 200).attempts == 2


@pytest.mark.parametrize(
    ("base_fail", "fault_fail", "affected"),
    [(0, 20, True), (0, 19, False), (10, 30, True), (10, 29, False), (100, 100, False)],
)
def test_a_rise_of_twenty_points_in_failures_is_an_effect(base_fail: int, fault_fail: int, affected: bool) -> None:
    base = Window(attempts=100, failures=base_fail, p95_s=0.1)
    fault = Window(attempts=100, failures=fault_fail, p95_s=0.1)
    assert scoring.journey_affected(base, fault) is affected


@pytest.mark.parametrize(
    ("base_p95", "fault_p95", "affected"),
    [(0.6, 1.2, True), (0.6, 1.19, False), (0.2, 0.9, False), (0.4, 1.0, False), (0.4, 1.01, True)],
)
def test_a_doubled_p95_over_one_second_is_an_effect(base_p95: float, fault_p95: float, affected: bool) -> None:
    base = Window(attempts=50, failures=0, p95_s=base_p95)
    fault = Window(attempts=50, failures=0, p95_s=fault_p95)
    assert scoring.journey_affected(base, fault) is affected


def test_a_window_where_no_attempt_started_is_an_effect() -> None:
    assert scoring.journey_affected(Window(50, 0, 0.1), Window(0, 0, None)) is True


def test_served_share_cannot_be_judged_without_orders() -> None:
    assert scoring.served_share([], set(), 0, 100) is None
    orders = [{"id": "a", "t": 10.0}, {"id": "b", "t": 20.0}]
    assert scoring.served_share(orders, {"a"}, 0, 100) == 0.5


def test_outcome_marks_journeys_and_back_office_functions() -> None:
    records = attempts("user_a", 0, 50) + attempts("user_a", 100, 50, failures=50) + attempts("user_b", 0, 50)
    records += attempts("user_b", 100, 50)
    orders = [{"id": f"o{i}", "t": float(i * 10)} for i in range(20)]  # ten in each window
    backoffice = {"orders": orders, "in_ledger": [f"o{i}" for i in range(10)], "in_fraud_log": [o["id"] for o in orders]}
    result = scoring.outcome(TEST, records, backoffice, JOURNEYS, BACKOFFICE)
    assert result.affected == {"Function A", "Record orders"}
    assert result.unjudged == set()
    assert result.backoffice["Record orders"] == {"baseline_share": 1.0, "fault_share": 0.0, "affected": True}


def test_a_ledger_that_could_not_be_read_leaves_the_function_unjudged() -> None:
    orders = [{"id": "o1", "t": 10.0}, {"id": "o2", "t": 150.0}]
    result = scoring.outcome(TEST, [], {"orders": orders, "in_ledger": None, "in_fraud_log": []}, {}, BACKOFFICE)
    assert "Record orders" in result.unjudged
    assert "Screen orders" not in result.unjudged


def test_a_fault_window_without_orders_leaves_the_back_office_unjudged() -> None:
    orders = [{"id": "o1", "t": 10.0}]
    result = scoring.outcome(TEST, [], {"orders": orders, "in_ledger": ["o1"], "in_fraud_log": ["o1"]}, {}, BACKOFFICE)
    assert result.unjudged == {"Record orders", "Screen orders"}


def test_score_counts_every_judged_pair() -> None:
    o1 = scoring.TestOutcome("stop:x", "stop", "x", affected={"A"})
    o2 = scoring.TestOutcome("stop:y", "stop", "y", affected={"A", "B"}, unjudged={"C"})
    predictions = {"stop:x": ["A", "B"], "stop:y": ["A", "B", "C"]}
    s = scoring.score([o1, o2], predictions, ["A", "B", "C"])
    # stop:x: A true positive, B false positive, C true negative. stop:y: A and B true positives, C left out.
    assert (s.tp, s.fp, s.fn, s.tn) == (3, 1, 0, 1)
    assert s.tests == 2


def test_score_exact_counts_tests_with_no_wrong_pair() -> None:
    o1 = scoring.TestOutcome("t1", "stop", "x", affected={"A"})
    o2 = scoring.TestOutcome("t2", "stop", "y", affected=set())
    s = scoring.score([o1, o2], {"t1": ["A"], "t2": ["B"]}, ["A", "B"])
    assert s.exact == 1
    assert s.precision == 0.5 and s.recall == 1.0


def test_errors_list_every_wrong_pair() -> None:
    o = scoring.TestOutcome("t1", "stop", "x", affected={"A"})
    assert scoring.errors([o], {"t1": ["B"]}, ["A", "B"]) == [
        {"test": "t1", "function": "A", "predicted": False, "measured": True},
        {"test": "t1", "function": "B", "predicted": True, "measured": False},
    ]


def test_precision_and_recall_are_undefined_without_positives() -> None:
    s = scoring.Score()
    assert s.precision is None and s.recall is None
