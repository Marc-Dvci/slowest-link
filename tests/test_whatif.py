"""What-if: notice parsing, component matching, broken promises and restore order."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
import relate
from hypothesis import given
from hypothesis import strategies as st

from slowest_link import whatif
from tests.graphs import mini_shop


@pytest.fixture
def conn() -> Iterator[relate.Connection]:
    c = mini_shop()
    yield c
    c.close()


# The mini shop's nine one-line descriptions score far below the shop's plan (full-text scores grow with the number
# of components), so its search tests run with no floor. The floor itself is tested on the real plan, below.
NO_FLOOR = 0.0


@pytest.mark.parametrize(
    ("text", "minutes"),
    [
        ("estimated restore 3 hours", 180),
        ("down for 2 h 28 min", 148),
        ("2 hours and 28 minutes", 148),
        ("expect 90 minutes", 90),
        ("1.5 hours", 90),
        ("ETA 45 min", 45),
        ("no estimate yet", None),
        ("region eu-west-1 is degraded", None),
    ],
)
def test_parse_duration_reads_the_first_duration(text: str, minutes: int | None) -> None:
    assert whatif.parse_duration(text) == minutes


@given(st.integers(min_value=1, max_value=72))
def test_parse_duration_reads_any_whole_hours(hours: int) -> None:
    assert whatif.parse_duration(f"outage, about {hours} hours") == hours * 60


def test_a_component_named_in_the_notice_matches_exactly(conn: relate.Connection) -> None:
    found = whatif.match_components(conn, "The catalog service returns errors", NO_FLOOR)
    assert found[0] == {"component": "catalog", "how": "named", "score": None}


def test_a_name_inside_another_word_does_not_match(conn: relate.Connection) -> None:
    named = [m for m in whatif.match_components(conn, "the webshop is slow", NO_FLOOR) if m["how"] == "named"]
    assert named == []


def test_a_description_matches_through_full_text_search(conn: relate.Connection) -> None:
    found = whatif.match_components(conn, "Our managed PostgreSQL is unavailable", NO_FLOOR)
    assert [m["component"] for m in found] == ["db"]
    assert found[0]["how"] == "search"


def test_a_notice_about_nothing_in_the_plan_matches_nothing(conn: relate.Connection) -> None:
    result = whatif.what_if(conn, "The office coffee machine is broken", min_score=NO_FLOOR)
    assert result.components == [] and result.affected == []


def test_a_stated_outage_longer_than_the_promise_breaks_it(conn: relate.Connection) -> None:
    result = whatif.what_if(conn, "PostgreSQL database down, restore expected in 3 hours", min_score=NO_FLOOR)
    broken = {row["function"] for row in result.broken}
    assert broken == {"View product", "Place order"}
    kept = {row["function"] for row in result.affected if not row["broken"]}
    assert kept == {"Record orders"}  # promises 24 h


def test_without_a_duration_the_recovery_objective_is_used(conn: relate.Connection) -> None:
    result = whatif.what_if(conn, "the mail service is down", min_score=NO_FLOOR)
    place = next(row for row in result.affected if row["function"] == "Place order")
    assert place["expected_outage_min"] == 60
    assert place["broken"] is False  # 60 is not longer than the 60 min promise


def test_broken_promises_come_first_in_the_impact_list(conn: relate.Connection) -> None:
    result = whatif.what_if(conn, "PostgreSQL database down for 3 hours", min_score=NO_FLOOR)
    assert [row["broken"] for row in result.affected] == sorted(
        (row["broken"] for row in result.affected), reverse=True
    )


def test_the_restore_order_puts_dependencies_first(conn: relate.Connection) -> None:
    result = whatif.what_if(conn, "catalog and db are both down for 2 hours", min_score=NO_FLOOR)
    components = [c for c in result.restore_order if c in {"catalog", "db"}]
    assert components == ["db", "catalog"]


def test_the_view_changes_who_is_reached(conn: relate.Connection) -> None:
    evidence = whatif.what_if(conn, "the ads service is down for 2 hours", view="evidence", min_score=NO_FLOOR)
    architecture = whatif.what_if(conn, "the ads service is down for 2 hours", view="architecture", min_score=NO_FLOOR)
    assert evidence.affected == []  # no trace shows a call to ads
    assert {row["function"] for row in architecture.affected} == {"View product", "Place order", "Show ads"}


def test_to_dict_lists_the_broken_functions(conn: relate.Connection) -> None:
    data = whatif.what_if(conn, "PostgreSQL database down for 3 hours", min_score=NO_FLOOR).to_dict()
    assert set(data["broken"]) == {"View product", "Place order"}
    assert data["outage_min"] == 180


PLAN_NOTICES = [
    ("Our managed PostgreSQL database is down. Estimated restore: 3 hours.", "astronomy-db"),
    ("Our Valkey cache cluster is degraded.", "valkey-cart"),
    ("The CDN serving product images is down.", "image-provider"),
    ("Feature flag evaluation errors across all services.", "flagd"),
    ("Envoy proxy crash at the front door.", "frontend-proxy"),
    ("Fraud screening is delayed.", "fraud-detection"),
]


@pytest.fixture(scope="module")
def plan() -> Iterator[relate.Connection]:
    from pathlib import Path

    from slowest_link.store import open_store

    with open_store(Path(__file__).resolve().parents[1] / "plan", read_only=True) as c:
        yield c


@pytest.mark.parametrize(("notice", "component"), PLAN_NOTICES)
def test_a_notice_about_a_component_of_the_plan_finds_it_first(
    plan: relate.Connection, notice: str, component: str
) -> None:
    assert whatif.match_components(plan, notice)[0]["component"] == component


@pytest.mark.parametrize(
    "notice",
    [
        "The coffee machine on the third floor is out of order.",
        "Customer support phone lines are busy.",
        "Our HR portal will be down for maintenance tonight.",
    ],
)
def test_a_notice_unrelated_to_the_plan_matches_no_component(plan: relate.Connection, notice: str) -> None:
    # "order" and "customer" appear in component descriptions; one common word is not enough to name a component.
    assert whatif.match_components(plan, notice) == []
