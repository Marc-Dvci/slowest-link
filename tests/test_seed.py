"""The seed: reading the published diagram and the plan's spreadsheets into a Relate vault."""

from __future__ import annotations

from pathlib import Path

import pytest

from slowest_link import seed
from slowest_link.store import open_store, rows

ROOT = Path(__file__).resolve().parents[1]

DIAGRAM = """%% comment line -->
graph TD
subgraph Service Diagram
web(Web):::ts
queue[(queue<br/>Kafka)]:::java
postgresql[(astronomy-db<br/>PostgreSQL)]
web -->|gRPC| api
web ---->|HTTP| api
api --> postgresql
queue -->|TCP| ledger
load-generator -->|HTTP| web
agent -.->|HTTP| web
end
"""


def test_arrows_of_any_length_become_declared_calls() -> None:
    calls = seed.parse_mermaid(DIAGRAM)
    assert seed.DeclaredCall("web", "api", "gRPC") in calls
    assert seed.DeclaredCall("web", "api", "HTTP") in calls


def test_aliases_name_components_as_the_shop_deploys_them() -> None:
    calls = seed.parse_mermaid(DIAGRAM)
    assert seed.DeclaredCall("api", "astronomy-db", "") in calls


def test_a_consumer_depends_on_its_queue_not_the_reverse() -> None:
    calls = seed.parse_mermaid(DIAGRAM)
    assert seed.DeclaredCall("ledger", "kafka", "TCP") in calls


def test_clients_and_add_ons_are_not_components() -> None:
    calls = seed.parse_mermaid(DIAGRAM)
    assert all("load-generator" not in (c.source, c.target) for c in calls)
    assert all("agent" not in (c.source, c.target) for c in calls)


def test_diagram_nodes_skips_comments_edges_and_clients() -> None:
    assert seed.diagram_nodes(DIAGRAM) == {"web", "kafka", "astronomy-db"}


def test_the_published_diagram_declares_34_calls_between_deployed_components() -> None:
    text = (ROOT / "sources" / "otel-demo-architecture.mmd").read_text(encoding="utf-8")
    calls = seed.parse_mermaid(text)
    assert len(calls) == 34
    assert seed.DeclaredCall("product-catalog", "astronomy-db", "") in calls


def test_seeding_the_committed_sources_builds_the_plan(tmp_path: Path) -> None:
    counts = seed.seed(tmp_path / "plan", ROOT / "sources")
    assert counts == {"components": 20, "functions": 9, "declared_calls": 34}
    with open_store(tmp_path / "plan", read_only=True) as conn:
        assert rows(conn, "MATCH (f:Function {name: 'Place an order'}) RETURN f.promise_min AS p")[0]["p"] == 60
        assert rows(conn, "MATCH ()-[r:CALLS]->() WHERE r.declared RETURN count(r) AS n")[0]["n"] == 34
    note = (tmp_path / "plan" / "Function" / "Place an order.md").read_text(encoding="utf-8")
    assert "promise_min: 60" in note and "[[Service/checkout]]" in note


def test_seeding_refuses_a_folder_that_holds_a_store(tmp_path: Path) -> None:
    seed.seed(tmp_path / "plan", ROOT / "sources")
    with pytest.raises(FileExistsError):
        seed.seed(tmp_path / "plan", ROOT / "sources")


def _sources(tmp_path: Path, objectives: str, bia: str) -> Path:
    src = tmp_path / "src"
    src.mkdir()
    (src / "otel-demo-architecture.mmd").write_text("graph TD\nweb --> api\n", encoding="utf-8")
    (src / "recovery-objectives.csv").write_text(objectives, encoding="utf-8")
    (src / "business-impact-analysis.csv").write_text(bia, encoding="utf-8")
    return src


HEAD_O = "component,kind,recovery_min,owner,description\n"
HEAD_B = "function,journeys,promise_min,critical,enters,uses,description\n"


def test_a_diagram_component_without_an_objective_is_refused(tmp_path: Path) -> None:
    src = _sources(tmp_path, HEAD_O + "web,Service,15,T,d\n", HEAD_B)
    with pytest.raises(ValueError, match="api"):
        seed.seed(tmp_path / "plan", src)


def test_an_unknown_component_kind_is_refused(tmp_path: Path) -> None:
    src = _sources(tmp_path, HEAD_O + "web,Service,15,T,d\napi,Lambda,15,T,d\n", HEAD_B)
    with pytest.raises(ValueError, match="Lambda"):
        seed.seed(tmp_path / "plan", src)


def test_a_function_naming_an_unknown_component_is_refused(tmp_path: Path) -> None:
    src = _sources(
        tmp_path, HEAD_O + "web,Service,15,T,d\napi,Service,15,T,d\n", HEAD_B + "F,j,60,true,web,web;nope,d\n"
    )
    with pytest.raises(ValueError, match="nope"):
        seed.seed(tmp_path / "plan", src)
