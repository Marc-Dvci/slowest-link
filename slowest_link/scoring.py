"""Score the outage tests: what each fault did to each function, against what each view predicted.

The rules are the ones `experiments/PROTOCOL.md` fixed before the tests ran:

- A journey attempt belongs to the window its start time falls in: baseline [t_baseline, t_fault), fault
  [t_fault, t_fault_end).
- A journey is affected when its failure rate rises by at least 20 percentage points over the baseline, or when its
  95th-percentile latency is at least twice the baseline's and above 1 second.
- A back-office function is affected when the share of orders it served falls by at least 20 points; a window without
  orders, or a ledger that could not be read, cannot be judged and is left out.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

FAILURE_RISE = 0.20
LATENCY_FACTOR = 2.0
LATENCY_FLOOR_S = 1.0
SERVED_DROP = 0.20


@dataclass(frozen=True)
class Window:
    attempts: int
    failures: int
    p95_s: float | None

    @property
    def failure_rate(self) -> float:
        return self.failures / self.attempts if self.attempts else 1.0


def p95(values: Sequence[float]) -> float | None:
    """Nearest-rank 95th percentile."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]


def window(records: Iterable[Mapping[str, Any]], journey: str, start: float, end: float) -> Window:
    picked = [r for r in records if r["journey"] == journey and start <= r["t"] < end]
    return Window(
        attempts=len(picked),
        failures=sum(1 for r in picked if not r["ok"]),
        p95_s=p95([float(r["latency_s"]) for r in picked]),
    )


def journey_affected(base: Window, fault: Window) -> bool:
    if fault.attempts == 0:
        return True  # no attempt even started: the journey was stuck for the whole window
    if fault.failure_rate - base.failure_rate >= FAILURE_RISE - 1e-9:
        return True
    if base.p95_s is None or fault.p95_s is None:
        return False
    return fault.p95_s >= LATENCY_FACTOR * base.p95_s and fault.p95_s > LATENCY_FLOOR_S


def served_share(orders: Sequence[Mapping[str, Any]], served: set[str], start: float, end: float) -> float | None:
    placed = [o["id"] for o in orders if start <= o["t"] < end]
    if not placed:
        return None
    return sum(1 for o in placed if o in served) / len(placed)


@dataclass
class TestOutcome:
    test: str
    kind: str
    target: str
    affected: set[str] = field(default_factory=set)
    unjudged: set[str] = field(default_factory=set)
    journeys: dict[str, dict[str, Any]] = field(default_factory=dict)
    backoffice: dict[str, dict[str, Any]] = field(default_factory=dict)
    recovery_s: dict[str, float | None] = field(default_factory=dict)
    not_recovered: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "test": self.test,
            "kind": self.kind,
            "target": self.target,
            "affected": sorted(self.affected),
            "unjudged": sorted(self.unjudged),
            "journeys": self.journeys,
            "backoffice": self.backoffice,
            "recovery_s": self.recovery_s,
            "not_recovered": self.not_recovered,
        }


def outcome(
    test: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
    backoffice: Mapping[str, Any] | None,
    journey_function: Mapping[str, str],
    backoffice_functions: Mapping[str, str],
) -> TestOutcome:
    """What one test did to every function.

    journey_function: prober journey -> function. backoffice_functions: "ledger" and "fraud" -> function.
    """
    result = TestOutcome(test=test["test"], kind=test["kind"], target=test["target"])
    t0, t1, t2 = float(test["t_baseline"]), float(test["t_fault"]), float(test["t_fault_end"])
    for journey, function in sorted(journey_function.items()):
        base, fault = window(records, journey, t0, t1), window(records, journey, t1, t2)
        hit = journey_affected(base, fault)
        result.journeys[journey] = {
            "function": function,
            "baseline": {"attempts": base.attempts, "failure_rate": round(base.failure_rate, 3), "p95_s": base.p95_s},
            "fault": {"attempts": fault.attempts, "failure_rate": round(fault.failure_rate, 3), "p95_s": fault.p95_s},
            "affected": hit,
        }
        if hit:
            result.affected.add(function)
    sources: dict[str, set[str] | None] = {"ledger": None, "fraud": None}
    orders: list[Mapping[str, Any]] = []
    if backoffice is not None:
        orders = list(backoffice.get("orders") or [])
        ledger = backoffice.get("in_ledger")
        sources = {"ledger": set(ledger) if ledger is not None else None, "fraud": set(backoffice.get("in_fraud_log") or [])}
    for source, function in backoffice_functions.items():
        served = sources.get(source)
        base_share = served_share(orders, served, t0, t1) if served is not None else None
        fault_share = served_share(orders, served, t1, t2) if served is not None else None
        judged = base_share is not None and fault_share is not None
        hit = bool(judged and fault_share is not None and base_share is not None and base_share - fault_share >= SERVED_DROP - 1e-9)
        result.backoffice[function] = {"baseline_share": base_share, "fault_share": fault_share, "affected": hit}
        if not judged:
            result.unjudged.add(function)
        elif hit:
            result.affected.add(function)
    result.recovery_s = dict(test.get("recovery_s") or {})
    result.not_recovered = list(test.get("not_recovered") or [])
    return result


@dataclass
class Score:
    tp: int = 0
    fp: int = 0
    fn: int = 0
    tn: int = 0
    exact: int = 0
    tests: int = 0

    @property
    def precision(self) -> float | None:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else None

    @property
    def recall(self) -> float | None:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "tp": self.tp,
            "fp": self.fp,
            "fn": self.fn,
            "tn": self.tn,
            "precision": None if self.precision is None else round(self.precision, 3),
            "recall": None if self.recall is None else round(self.recall, 3),
            "exact": self.exact,
            "tests": self.tests,
        }


def score(
    outcomes: Sequence[TestOutcome], predictions: Mapping[str, Mapping[str, Sequence[str]]], functions: Sequence[str]
) -> Score:
    """Compare every judged (fault, function) pair. predictions: test id -> predicted functions."""
    total = Score()
    for o in outcomes:
        predicted = set(predictions[o.test])
        judged = [f for f in functions if f not in o.unjudged]
        hits = 0
        for function in judged:
            p, m = function in predicted, function in o.affected
            total.tp += p and m
            total.fp += p and not m
            total.fn += m and not p
            total.tn += not p and not m
            hits += p == m
        total.tests += 1
        total.exact += hits == len(judged)
    return total


def errors(
    outcomes: Sequence[TestOutcome], predictions: Mapping[str, Mapping[str, Sequence[str]]], functions: Sequence[str]
) -> list[dict[str, Any]]:
    """Every pair a view got wrong, for the report."""
    wrong = []
    for o in outcomes:
        predicted = set(predictions[o.test])
        for function in functions:
            if function in o.unjudged:
                continue
            p, m = function in predicted, function in o.affected
            if p != m:
                wrong.append({"test": o.test, "function": function, "predicted": p, "measured": m})
    return wrong
