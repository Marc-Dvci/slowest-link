"""Writing evidence into the plan: observed calls, tests, and calls a function survived without."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
import relate

from slowest_link import checks, evidence
from slowest_link.store import rows
from slowest_link.traces import ObservedCall
from tests.graphs import mini_shop


@pytest.fixture
def conn() -> Iterator[relate.Connection]:
    c = mini_shop()
    yield c
    c.close()


def edge(conn: relate.Connection, a: str, b: str) -> dict[str, object]:
    found = rows(conn, "MATCH ({name: $a})-[r:CALLS]->({name: $b}) RETURN properties(r) AS p", {"a": a, "b": b})
    assert len(found) == 1
    return dict(found[0]["p"])


def test_plan_maps_read_journeys_consumers_and_components(conn: relate.Connection) -> None:
    journeys, consumers, components = evidence.plan_maps(conn)
    assert journeys == {"user_view": "View product", "user_order": "Place order", "user_ads": "Show ads"}
    assert consumers == {"ledger": "Record orders"}
    assert "db" in components and "View product" not in components


def test_an_observed_call_confirms_the_declared_edge(conn: relate.Connection) -> None:
    counts = evidence.apply_observed(conn, [ObservedCall("web", "ads", "sync", {"Show ads"}, 12)], "2026-11-14")
    assert counts == {"confirmed": 1, "added": 0}
    p = edge(conn, "web", "ads")
    assert p["declared"] is True and p["observed"] is True and p["journeys"] == ["Show ads"] and p["calls"] == 12


def test_an_observed_call_nobody_declared_is_added_as_hidden(conn: relate.Connection) -> None:
    evidence.apply_observed(conn, [ObservedCall("mail", "db", "sync", {"Place order"}, 3)], "2026-11-14")
    p = edge(conn, "mail", "db")
    assert p["declared"] is False and p["source"] == "traces"
    assert ("mail", "db") in {(h["source"], h["target"]) for h in checks.hidden_calls(conn)}


def test_a_new_import_replaces_the_previous_trace_evidence(conn: relate.Connection) -> None:
    evidence.apply_observed(conn, [ObservedCall("mail", "db", "sync", {"Place order"}, 3)], "2026-11-14")
    evidence.apply_observed(conn, [ObservedCall("web", "ads", "sync", {"Show ads"}, 1)], "2026-11-15")
    assert rows(conn, "MATCH ({name: 'mail'})-[r:CALLS]->({name: 'db'}) RETURN count(r) AS n")[0]["n"] == 0
    assert edge(conn, "proxy", "web")["observed"] is False  # not in the new import
    assert edge(conn, "web", "ads")["observed_on"] == "2026-11-15"


def test_an_observed_call_naming_an_unknown_component_is_refused(conn: relate.Connection) -> None:
    with pytest.raises(ValueError, match="ghost"):
        evidence.apply_observed(conn, [ObservedCall("web", "ghost", "sync", {"View product"}, 1)], "2026-11-14")


def test_a_test_is_written_as_a_note_linked_to_its_component(conn: relate.Connection) -> None:
    evidence.record_test(
        conn,
        {"name": "t1", "date": "2026-11-14", "kind": "stop", "target": "catalog", "affected": ["View product"],
         "recovery_s": {"user_view": 4.5}, "not_recovered": []},
    )  # fmt: skip
    found = rows(conn, "MATCH (t:Test)-[:EXERCISED]->(c) RETURN t.date AS d, c.name AS c, t.recovery_s AS r")
    assert found == [{"d": "2026-11-14", "c": "catalog", "r": [4.5]}]


def test_recording_the_same_test_twice_keeps_one_note(conn: relate.Connection) -> None:
    test = {"name": "t1", "date": "2026-11-14", "kind": "stop", "target": "catalog"}
    evidence.record_test(conn, test)
    evidence.record_test(conn, test)
    assert rows(conn, "MATCH (t:Test)-[e:EXERCISED]->() RETURN count(t) AS t, count(e) AS e")[0] == {"t": 1, "e": 1}


@pytest.mark.parametrize("missing", ["name", "date", "kind", "target"])
def test_a_test_without_a_required_field_is_refused(conn: relate.Connection, missing: str) -> None:
    test = {"name": "t1", "date": "2026-11-14", "kind": "stop", "target": "catalog"}
    del test[missing]
    with pytest.raises(ValueError, match=missing):
        evidence.record_test(conn, test)


def test_a_test_of_an_unknown_component_is_refused(conn: relate.Connection) -> None:
    with pytest.raises(ValueError, match="ghost"):
        evidence.record_test(conn, {"name": "t", "date": "2026-11-14", "kind": "stop", "target": "ghost"})


def test_survival_marks_the_calls_into_the_component_for_that_function(conn: relate.Connection) -> None:
    assert evidence.record_survival(conn, "Place order", "mail", "t-mail") == 1
    assert edge(conn, "orders", "mail")["survives_without"] == ["Place order"]
    assert "mail" not in checks.reach(conn, "evidence")["Place order"]


def test_survival_is_recorded_once(conn: relate.Connection) -> None:
    evidence.record_survival(conn, "Place order", "mail", "t-mail")
    assert evidence.record_survival(conn, "Place order", "mail", "t-mail-again") == 0


def test_survival_ignores_calls_outside_the_functions_traces(conn: relate.Connection) -> None:
    assert evidence.record_survival(conn, "View product", "mail", "t") == 0


def test_need_marks_an_asynchronous_call_the_function_cannot_lose(conn: relate.Connection) -> None:
    assert evidence.record_need(conn, "Place order", "queue", "t-queue") == 1
    assert edge(conn, "orders", "queue")["needed_by"] == ["Place order"]
    assert "queue" in checks.reach(conn, "evidence")["Place order"]


def test_need_is_recorded_once(conn: relate.Connection) -> None:
    evidence.record_need(conn, "Place order", "queue", "t-queue")
    assert evidence.record_need(conn, "Place order", "queue", "t-queue-again") == 0
