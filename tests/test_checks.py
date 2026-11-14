"""The checks, one behaviour per test, on the miniature shop in graphs.py."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
import relate

from slowest_link import checks
from tests.graphs import mini_shop


@pytest.fixture
def conn() -> Iterator[relate.Connection]:
    c = mini_shop()
    yield c
    c.close()


def by_function(findings: list[checks.Finding]) -> dict[str, checks.Finding]:
    return {f.function: f for f in findings}


def test_the_plan_view_checks_each_listed_component_on_its_own(conn: relate.Connection) -> None:
    found = by_function(checks.inversions(conn, "plan"))
    # Show ads lists ads (60 min) against a 30 min promise; the others list nothing slower than their promise.
    assert set(found) == {"Show ads"}
    assert found["Show ads"].component == "ads"
    assert found["Show ads"].path == ["ads"]


def test_the_architecture_view_follows_declared_calls_through(conn: relate.Connection) -> None:
    found = by_function(checks.inversions(conn, "architecture"))
    assert found["View product"].component == "db"
    assert found["View product"].value_min == 240
    assert found["View product"].path == ["proxy", "web", "catalog", "db"]
    # The architecture view ignores journeys, so Show ads reaches the database through the shared frontend.
    assert found["Show ads"].component == "db"


def test_the_evidence_view_keeps_only_calls_seen_in_the_functions_own_traces(conn: relate.Connection) -> None:
    found = by_function(checks.inversions(conn, "evidence"))
    assert set(found) == {"View product", "Place order"}
    # Place order's traces reach the catalogue only through orders, never straight from web.
    assert found["Place order"].path == ["proxy", "web", "orders", "catalog", "db"]
    assert "Show ads" not in found  # its traces never reach the database


def test_an_asynchronous_call_does_not_hold_a_promise(conn: relate.Connection) -> None:
    deps = checks.reach(conn, "evidence")
    assert "queue" not in deps["Place order"]
    assert "queue" in checks.reach(conn, "architecture")["Place order"]


def test_a_consumer_depends_on_its_queue(conn: relate.Connection) -> None:
    assert {"ledger", "queue", "db"} <= checks.reach(conn, "evidence")["Record orders"]


def test_the_slowest_link_prefers_the_shortest_path_to_it(conn: relate.Connection) -> None:
    found = by_function(checks.inversions(conn, "architecture"))
    # Place order reaches db through web -> catalog and through web -> orders -> catalog; the shorter path wins.
    assert found["Place order"].path == ["proxy", "web", "catalog", "db"]


def test_a_restore_chain_sums_recovery_times_along_the_path(conn: relate.Connection) -> None:
    found = by_function(checks.restore_chains(conn, "evidence"))
    assert found["Place order"].value_min == 15 + 15 + 30 + 30 + 240
    assert found["Place order"].path == ["proxy", "web", "orders", "catalog", "db"]


def test_a_chain_can_break_a_promise_no_single_component_breaks(conn: relate.Connection) -> None:
    conn.execute("MATCH (f:Function {name: 'Place order'}) SET f.promise_min = 300")
    assert "Place order" not in by_function(checks.inversions(conn, "evidence"))
    assert by_function(checks.restore_chains(conn, "evidence"))["Place order"].value_min == 330


def test_a_promise_equal_to_the_recovery_is_kept(conn: relate.Connection) -> None:
    conn.execute("MATCH (f:Function {name: 'View product'}) SET f.promise_min = 240")
    assert "View product" not in by_function(checks.inversions(conn, "evidence"))


def test_a_promise_one_minute_short_is_broken(conn: relate.Connection) -> None:
    conn.execute("MATCH (f:Function {name: 'View product'}) SET f.promise_min = 239")
    found = by_function(checks.inversions(conn, "evidence"))
    assert found["View product"].gap_min == 1


def test_paths_never_loop_through_a_cycle(conn: relate.Connection) -> None:
    for view in ("architecture", "evidence"):
        for finding in checks.restore_chains(conn, view):
            assert len(finding.path) == len(set(finding.path))


def test_a_call_no_one_declared_is_marked_on_the_path(conn: relate.Connection) -> None:
    conn.execute(
        "MATCH (w:Service {name: 'web'}), (m:Service {name: 'mail'}) "
        "CREATE (w)-[:CALLS {declared: false, observed: true, mode: 'sync', journeys: ['View product']}]->(m)"
    )
    conn.execute("MATCH (f:Function {name: 'View product'}) SET f.promise_min = 45")
    chains = by_function(checks.restore_chains(conn, "evidence"))
    assert chains["View product"].hidden_hops == []  # the longest chain still runs through the database
    conn.execute("MATCH (d:Datastore {name: 'db'}) SET d.recovery_min = 10")
    slow = by_function(checks.inversions(conn, "evidence"))["View product"]
    assert slow.component == "mail"
    assert slow.hidden_hops == ["web -> mail"]


def test_a_call_a_test_proved_survivable_is_left_out_for_that_function_only(conn: relate.Connection) -> None:
    assert "mail" in checks.reach(conn, "evidence")["Place order"]
    conn.execute(
        "MATCH (:Service {name: 'orders'})-[r:CALLS]->(:Service {name: 'mail'}) SET r.survives_without = ['Place order']"
    )
    assert "mail" not in checks.reach(conn, "evidence")["Place order"]
    assert "mail" in checks.reach(conn, "architecture")["Place order"]


def test_hidden_calls_list_observed_calls_nobody_declared(conn: relate.Connection) -> None:
    hidden = checks.hidden_calls(conn)
    assert [(h["source"], h["target"]) for h in hidden] == [("db", "proxy")]


def test_unseen_calls_list_declared_calls_no_trace_showed(conn: relate.Connection) -> None:
    assert [(u["source"], u["target"]) for u in checks.unseen_calls(conn)] == [("web", "ads")]


def test_plan_gaps_list_dependencies_the_plan_leaves_out(conn: relate.Connection) -> None:
    gaps = {g["function"]: [m["component"] for m in g["missing"]] for g in checks.plan_gaps(conn)}
    assert gaps["View product"] == ["db"]
    assert gaps["Place order"] == ["db", "mail", "catalog"]  # slowest first, then by name
    assert "Show ads" not in gaps


def test_untested_components_respect_the_date_boundary(conn: relate.Connection) -> None:
    conn.execute("MATCH (d:Datastore {name: 'db'}) CREATE (:Test {name: 't1', date: '2025-11-14'})-[:EXERCISED]->(d)")
    on_boundary = {u["component"] for u in checks.untested_components(conn, "evidence", "2025-11-14")}
    after = {u["component"] for u in checks.untested_components(conn, "evidence", "2025-11-15")}
    assert "db" not in on_boundary
    assert "db" in after


def test_only_critical_functions_count_for_untested_components(conn: relate.Connection) -> None:
    conn.execute("MATCH (f:Function) WHERE f.name <> 'Show ads' SET f.critical = false")
    assert checks.untested_components(conn, "evidence", "2025-01-01") == []


def test_shared_points_need_two_critical_functions(conn: relate.Connection) -> None:
    shared = {s["component"]: s["functions"] for s in checks.shared_points(conn, "evidence")}
    assert set(shared["db"]) == {"View product", "Place order", "Record orders"}
    assert "mail" not in shared  # only Place order uses it


def test_a_stop_test_that_left_a_journey_down_is_reported(conn: relate.Connection) -> None:
    conn.execute(
        "MATCH (c:Service {name: 'catalog'}) CREATE (:Test {name: 't2', date: '2026-11-14', kind: 'stop', "
        "not_recovered: ['user_view']})-[:EXERCISED]->(c)"
    )
    assert checks.not_self_recovering(conn) == [
        {"component": "catalog", "test": "t2", "date": "2026-11-14", "journeys": ["user_view"]}
    ]


def test_profile_reports_a_function_without_dependencies(conn: relate.Connection) -> None:
    conn.execute("CREATE (:Function {name: 'Lonely', promise_min: 10})")
    p = checks.profile(conn, "evidence", "Lonely")
    assert p["components"] == [] and p["slowest"] is None


def test_profile_refuses_an_unknown_function(conn: relate.Connection) -> None:
    with pytest.raises(KeyError):
        checks.profile(conn, "evidence", "Nope")


def test_run_all_returns_every_check_in_every_view(conn: relate.Connection) -> None:
    result = checks.run_all(conn, "2025-11-14")
    assert set(result["inversions"]) == set(checks.VIEWS)
    assert set(result) >= {"plan_gaps", "hidden_calls", "unseen_calls", "untested_components", "shared_points"}


def test_an_asynchronous_call_a_test_proved_needed_holds_the_promise(conn: relate.Connection) -> None:
    assert "queue" not in checks.reach(conn, "evidence")["Place order"]
    conn.execute(
        "MATCH (:Service {name: 'orders'})-[r:CALLS]->(:Queue {name: 'queue'}) SET r.needed_by = ['Place order']"
    )
    assert "queue" in checks.reach(conn, "evidence")["Place order"]
    assert "queue" not in checks.reach(conn, "evidence")["View product"]
