"""Build the plan vault from the continuity team's inputs.

Three inputs, all in `sources/`:

- the shop's published service diagram (Mermaid), which gives the declared calls between components;
- the business impact analysis: each function's recovery promise, its entry point and the components the plan lists;
- each component's declared recovery objective, owner and description.

The seed runs once. From then on the vault is the plan: people edit its notes, and the trace import adds evidence.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

import relate

from slowest_link.store import create_vault, open_store

# Diagram node ids that name a component differently from its compose service.
ALIASES = {"cache": "valkey-cart", "queue": "kafka", "postgresql": "astronomy-db"}

# Diagram nodes that are clients or optional add-ons, not components of the deployed shop.
NOT_COMPONENTS = {"Internet", "load-generator", "react-native-app", "agent", "chatbot", "mcp"}

# Components that other components consume from rather than call: the diagram draws the arrow from the queue to the
# consumer (data flow); the dependency runs from the consumer to the queue.
QUEUES = {"kafka"}

# Full-text index over each component's name and description: the what-if maps an outage notice to components with it.
TEXT_INDEX = (
    "CREATE FULLTEXT INDEX component_text IF NOT EXISTS FOR (n:Service|Datastore|Queue) ON EACH [n.name, n.description]"
)

_EDGE = re.compile(r"^\s*([\w-]+)\s*(-\.->|-{2,}>)\s*(?:\|([^|]*)\|)?\s*([\w-]+)\s*$")
_NODE = re.compile(r"^\s*([\w-]+)\s*[\[(]")


@dataclass(frozen=True)
class DeclaredCall:
    source: str
    target: str
    protocol: str


def component_name(node_id: str) -> str:
    return ALIASES.get(node_id, node_id)


def parse_mermaid(text: str) -> list[DeclaredCall]:
    """Return the declared calls between deployed components, as dependencies (caller -> callee)."""
    calls: list[DeclaredCall] = []
    for line in text.splitlines():
        if line.lstrip().startswith("%%"):
            continue
        match = _EDGE.match(line)
        if not match:
            continue
        src, _arrow, label, dst = match.groups()
        if src in NOT_COMPONENTS or dst in NOT_COMPONENTS:
            continue
        source, target = component_name(src), component_name(dst)
        if source in QUEUES:
            source, target = target, source
        calls.append(DeclaredCall(source, target, (label or "").strip()))
    return calls


def diagram_nodes(text: str) -> set[str]:
    """Every component the diagram names, aliases applied, clients and add-ons removed."""
    names: set[str] = set()
    for line in text.splitlines():
        if "-->" in line or "-.->" in line or line.lstrip().startswith(("%%", "classDef", "subgraph", "graph")):
            continue
        match = _NODE.match(line)
        if match and match.group(1) not in NOT_COMPONENTS:
            names.add(component_name(match.group(1)))
    return names


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _split(value: str) -> list[str]:
    return [item for item in (part.strip() for part in value.split(";")) if item]


def seed(vault: Path, sources: Path) -> dict[str, int]:
    """Create the plan vault from the three inputs and return what was written."""
    diagram = (sources / "otel-demo-architecture.mmd").read_text(encoding="utf-8")
    objectives = read_csv(sources / "recovery-objectives.csv")
    functions = read_csv(sources / "business-impact-analysis.csv")
    calls = parse_mermaid(diagram)

    known = {row["component"] for row in objectives}
    missing = (diagram_nodes(diagram) | {c.source for c in calls} | {c.target for c in calls}) - known
    if missing:
        raise ValueError(f"components in the diagram without a recovery objective: {sorted(missing)}")

    create_vault(vault)
    with open_store(vault) as conn:
        conn.autocommit = False
        for row in objectives:
            _create_component(conn, row)
        for row in functions:
            _create_function(conn, row, known)
        for call in calls:
            conn.execute(
                "MATCH (a {name: $source}), (b {name: $target}) "
                "WHERE NOT a:Function AND NOT b:Function "
                "CREATE (a)-[:CALLS {declared: true, observed: false, mode: 'unknown', protocol: $protocol, "
                "source: 'published architecture'}]->(b)",
                {"source": call.source, "target": call.target, "protocol": call.protocol},
            )
        conn.commit()
        conn.autocommit = True
        conn.execute(TEXT_INDEX)
    return {"components": len(objectives), "functions": len(functions), "declared_calls": len(calls)}


def _create_component(conn: relate.Connection, row: dict[str, str]) -> None:
    kind = row["kind"]
    if kind not in {"Service", "Datastore", "Queue"}:
        raise ValueError(f"unknown component kind {kind!r} for {row['component']}")
    conn.execute(
        f"CREATE (:{kind} {{name: $name, recovery_min: $recovery, owner: $owner, description: $description}})",
        {
            "name": row["component"],
            "recovery": int(row["recovery_min"]),
            "owner": row["owner"],
            "description": row["description"],
        },
    )


def _create_function(conn: relate.Connection, row: dict[str, str], known: set[str]) -> None:
    uses = _split(row["uses"])
    unknown = [name for name in [row["enters"], *uses] if name not in known]
    if unknown:
        raise ValueError(f"{row['function']} names unknown components: {unknown}")
    conn.execute(
        "CREATE (:Function {name: $name, promise_min: $promise, critical: $critical, journeys: $journeys, "
        "description: $description})",
        {
            "name": row["function"],
            "promise": int(row["promise_min"]),
            "critical": row["critical"].strip().lower() == "true",
            "journeys": _split(row["journeys"]),
            "description": row["description"],
        },
    )
    conn.execute(
        "MATCH (f:Function {name: $name}), (e {name: $enters}) WHERE NOT e:Function CREATE (f)-[:ENTERS]->(e)",
        {"name": row["function"], "enters": row["enters"]},
    )
    for component in uses:
        conn.execute(
            "MATCH (f:Function {name: $name}), (c {name: $component}) WHERE NOT c:Function CREATE (f)-[:USES]->(c)",
            {"name": row["function"], "component": component},
        )
