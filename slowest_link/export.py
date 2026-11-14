"""Copy the plan graph as one Cypher script: for the browser page (Relate's WebAssembly build runs it in memory) and
for the guard, which tries a change on an in-memory copy and leaves the vault untouched."""

from __future__ import annotations

import json
import re
from typing import Any

import relate

from slowest_link.seed import TEXT_INDEX
from slowest_link.store import rows

_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def literal(value: Any) -> str:
    """A Cypher literal for a property value (strings, numbers, booleans and lists of them)."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value)  # double quotes, with backslashes and quotes escaped: valid Cypher
    if isinstance(value, list | tuple):
        return "[" + ", ".join(literal(v) for v in value) + "]"
    raise TypeError(f"cannot write {type(value).__name__} as a Cypher literal")


def _map(props: dict[str, Any]) -> str:
    items = []
    for key in sorted(props):
        if props[key] is None:
            continue
        if not _NAME.match(key):
            raise ValueError(f"property name {key!r} is not a plain identifier")
        items.append(f"{key}: {literal(props[key])}")
    return "{" + ", ".join(items) + "}"


def export_cypher(conn: relate.Connection) -> str:
    """The whole graph as a script: one CREATE for every node and relationship, then the full-text index."""
    nodes = rows(conn, "MATCH (n) RETURN elementId(n) AS id, labels(n) AS labels, properties(n) AS props ORDER BY id")
    rels = rows(
        conn,
        "MATCH (a)-[r]->(b) RETURN elementId(a) AS a, elementId(b) AS b, type(r) AS type, properties(r) AS props "
        "ORDER BY a, type, b",
    )
    var = {row["id"]: f"n{i}" for i, row in enumerate(nodes)}
    parts = []
    for row in nodes:
        labels = "".join(f":{label}" for label in sorted(row["labels"]) if _NAME.match(label))
        parts.append(f"({var[row['id']]}{labels} {_map(dict(row['props']))})")
    for row in rels:
        if not _NAME.match(row["type"]):
            raise ValueError(f"relationship type {row['type']!r} is not a plain identifier")
        parts.append(f"({var[row['a']]})-[:{row['type']} {_map(dict(row['props']))}]->({var[row['b']]})")
    return "CREATE " + ",\n       ".join(parts) + ";\n" + TEXT_INDEX + ";\n"


def copy_to_memory(conn: relate.Connection) -> relate.Connection:
    """An in-memory copy of the graph, safe to change."""
    script = export_cypher(conn)
    copy = relate.connect(":memory:")
    for statement in (s.strip() for s in script.split(";\n")):
        if statement:
            copy.execute(statement)
    return copy
