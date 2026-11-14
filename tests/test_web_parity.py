"""The browser page answers as the command line does.

web/test/parity.json holds the Python answers for a set of notices and planned calls. This test proves the file
matches the Python code on the committed plan; `node web/test/parity.mjs` (CI's web job) proves the browser code,
running on Relate's WebAssembly build, gives the same answers. The page's data must match the vault too.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from slowest_link import checks, guard, whatif
from slowest_link.export import export_cypher
from slowest_link.store import open_store

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "web" / "test" / "parity.json"

NOTICES = [
    "Our managed PostgreSQL database is down. Estimated restore: 3 hours.",
    "Kafka brokers unavailable, recovery expected in 2 hours.",
    "Card payments are failing at the payment service, ETA 45 minutes.",
    "The cart cache (valkey-cart) is lost; rebuilding for 90 minutes.",
    "flagd and frontend-proxy are both down for 2 h 28 min",
    "The office coffee machine is broken",
    "The coffee machine on the third floor is out of order.",
    "Customer support phone lines are busy.",
]
CALLS = [
    ("frontend", "product-catalog", ["Browse the shop"]),
    ("checkout", "recommendation", ["Place an order"]),
    ("frontend", "ad", ["View cart"]),
    ("cart", "flagd", ["View cart"]),
]


def python_answers() -> dict[str, Any]:
    out: dict[str, Any] = {"whatif": [], "guard": []}
    with open_store(ROOT / "plan", read_only=True) as conn:
        for notice in NOTICES:
            for view in checks.VIEWS:
                r = whatif.what_if(conn, notice, view).to_dict()
                out["whatif"].append({"notice": notice, "view": view, **r})
        for source, target, fns in CALLS:
            g = guard.simulate_call(conn, source, target, fns)
            out["guard"].append(
                {
                    "source": source,
                    "target": target,
                    "functions": fns,
                    "new": sorted((f["check"], f["function"], f["value_min"]) for f in g.new),
                    "worse": sorted((f["check"], f["function"], f["was_min"], f["value_min"]) for f in g.worse),
                }
            )
    return json.loads(json.dumps(out))  # tuples become lists, as in the stored file


def test_the_parity_fixture_matches_the_python_answers() -> None:
    assert json.loads(FIXTURE.read_text(encoding="utf-8")) == python_answers()


def test_the_pages_graph_is_the_committed_vault() -> None:
    with open_store(ROOT / "plan", read_only=True) as conn:
        assert (ROOT / "web" / "data" / "graph.cypher").read_text(encoding="utf-8") == export_cypher(conn)


def test_the_pages_queries_are_the_checks_queries() -> None:
    stored = json.loads((ROOT / "web" / "data" / "queries.json").read_text(encoding="utf-8"))
    assert stored == checks.query_texts()


if __name__ == "__main__":
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(json.dumps(python_answers(), indent=2) + "\n", encoding="utf-8")
    print(f"wrote {FIXTURE.relative_to(ROOT)}")
