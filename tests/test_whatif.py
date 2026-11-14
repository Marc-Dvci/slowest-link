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
    found = whatif.match_components(conn, "The catalog service returns errors")
    assert found[0] == {"component": "catalog", "how": "named", "score": None}


def test_a_name_inside_another_word_does_not_match(conn: relate.Connection) -> None:
    named = [m for m in whatif.match_components(conn, "the webshop is slow") if m["how"] == "named"]
    assert named == []


def test_a_description_matches_through_full_text_search(conn: relate.Connection) -> None:
    found = whatif.match_components(conn, "Our managed PostgreSQL is unavailable")
    assert [m["component"] for m in found] == ["db"]
    assert found[0]["how"] == "search"


def test_a_notice_about_nothing_in_the_plan_matches_nothing(conn: relate.Connection) -> None:
    result = whatif.what_if(conn, "The office coffee machine is broken")
    assert result.components == [] and result.affected == []


def test_a_stated_outage_longer_than_the_promise_breaks_it(conn: relate.Connection) -> None:
    result = whatif.what_if(conn, "PostgreSQL database down, restore expected in 3 hours")
    broken = {row["function"] for row in result.broken}
    assert broken == {"View product", "Place order"}
    kept = {row["function"] for row in result.affected if not row["broken"]}
    assert kept == {"Record orders"}  # promises 24 h


def test_without_a_duration_the_recovery_objective_is_used(conn: relate.Connection) -> None:
    result = whatif.what_if(conn, "the mail service is down")
    place = next(row for row in result.affected if row["function"] == "Place order")
    assert place["expected_outage_min"] == 60
    assert place["broken"] is False  # 60 is not longer than the 60 min promise


def test_broken_promises_come_first_in_the_impact_list(conn: relate.Connection) -> None:
    result = whatif.what_if(conn, "PostgreSQL database down for 3 hours")
    assert [row["broken"] for row in result.affected] == sorted(
        (row["broken"] for row in result.affected), reverse=True
    )


def test_the_restore_order_puts_dependencies_first(conn: relate.Connection) -> None:
    result = whatif.what_if(conn, "catalog and db are both down for 2 hours")
    components = [c for c in result.restore_order if c in {"catalog", "db"}]
    assert components == ["db", "catalog"]


def test_the_view_changes_who_is_reached(conn: relate.Connection) -> None:
    evidence = whatif.what_if(conn, "the ads service is down for 2 hours", view="evidence")
    architecture = whatif.what_if(conn, "the ads service is down for 2 hours", view="architecture")
    assert evidence.affected == []  # no trace shows a call to ads
    assert {row["function"] for row in architecture.affected} == {"View product", "Place order", "Show ads"}


def test_to_dict_lists_the_broken_functions(conn: relate.Connection) -> None:
    data = whatif.what_if(conn, "PostgreSQL database down for 3 hours").to_dict()
    assert set(data["broken"]) == {"View product", "Place order"}
    assert data["outage_min"] == 180
