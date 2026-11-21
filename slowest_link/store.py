"""Open the Relate store that holds the continuity plan.

The plan is a Relate directory store with the Markdown codec: one note per function and component, so the
continuity team edits it like documents and every change is a reviewable diff. Relate opens the folder as a graph.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import relate

ENGINE_DIR = ".relate"

# The manifest of an empty Markdown vault, as `relate --snapshot-format markdown` writes it (Relate 1.0.1; 1.2.0 opens
# it as is). Writing it lets Python create a vault: the Python binding opens a store with the codec its manifest names.
EMPTY_MARKDOWN_MANIFEST: dict[str, Any] = {
    "codec": "markdown",
    "checkpoint_lsn": 0,
    "commit_ts": 0,
    "value_encoding": 2,
    "next_node_id": 1,
    "next_rel_id": 1,
    "indexes": [],
    "constraints": [],
    "theater": {
        "databases": {"neo4j": [25, False], "system": [25, False], "system_ontologies": [25, False]},
        "index_details": {},
        "index_options": {},
        "graph_types": {},
        "current_graph_type": {"node_types": [], "edge_types": [], "constraints": [], "drop_constraint_names": []},
        "derived_constraints": {},
    },
    "read_only": False,
    "learned": {"keys": {}, "rel_types": [], "raw_files": [], "folded_keys": []},
    "embeddings": {},
    "files": {},
    "node_ids": {},
    "rel_ids": {},
}


def create_vault(path: Path) -> None:
    """Create an empty Markdown vault at `path`. Refuses a folder that already holds a store."""
    engine = path / ENGINE_DIR
    if engine.exists():
        raise FileExistsError(f"{path} already holds a Relate store")
    engine.mkdir(parents=True)
    (engine / "manifest.json").write_text(json.dumps(EMPTY_MARKDOWN_MANIFEST, indent=2), encoding="utf-8")


@contextmanager
def open_store(path: Path | str, read_only: bool = False) -> Iterator[relate.Connection]:
    """Open a Relate store (a vault folder, a `.rl` file or ':memory:') and close it on exit."""
    target = str(path)
    if target != ":memory:" and not read_only and not Path(target).exists():
        raise FileNotFoundError(f"no Relate store at {target}")
    conn = relate.connect(target, read_only=read_only)
    try:
        yield conn
    finally:
        conn.close()


def rows(conn: relate.Connection, query: str, params: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    """Run one Cypher statement and return its rows as plain dicts."""
    cursor = conn.execute(query, dict(params or {}))
    return [dict(row) for row in cursor]
