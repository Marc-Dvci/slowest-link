"""MCP server: the checks as tools for any agent (Claude Code, Cursor, Codex and others).

    python -m slowest_link mcp [--vault plan]

Every tool opens the plan read-only, so an agent can explore and ask what-ifs but never change the plan. Numbers in
an answer must come from these tools: the server's instructions say so, and the skill repeats it.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import relate
from mcp.server.mcpserver import MCPServer

from slowest_link import checks, guard, whatif
from slowest_link.store import open_store, rows

ROW_CAP = 200

INSTRUCTIONS = """\
Slowest Link holds a business continuity plan as a graph: functions (user journeys and back-office work) with a
recovery promise in minutes (promise_min), the components they run on with the recovery time their owners declared
(recovery_min), and the calls between components. Each call says whether the published architecture declares it
(declared), whether traces show it (observed), for which functions (journeys), whether the caller waits (mode: sync or
async), and which functions an outage test proved survive without it (survives_without).

Three views: plan (the plan's own list per function), architecture (declared calls, followed through) and evidence
(calls in each function's own traces, synchronous, minus proven survivals). Prefer the evidence view and say which
view an answer uses.

Every number you state must come from a tool result. Quote the path that explains a finding.
"""


def plain(value: Any) -> Any:
    """Relate values as JSON-ready data."""
    if isinstance(value, relate.Node):
        return {"labels": list(value.labels), **{k: plain(v) for k, v in value.properties.items()}}
    if isinstance(value, relate.Relationship):
        return {"type": value.type, **{k: plain(v) for k, v in value.properties.items()}}
    if isinstance(value, relate.Path):
        return {"nodes": [plain(n) for n in value.nodes], "relationships": [plain(r) for r in value.relationships]}
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [plain(v) for v in value]
    if isinstance(value, dt.date | dt.datetime):
        return value.isoformat()
    return value


def build_server(vault: Path) -> MCPServer:
    server: MCPServer = MCPServer(name="slowest-link", instructions=INSTRUCTIONS)

    @server.tool()
    def list_functions() -> list[dict[str, Any]]:
        """Every function in the plan with its recovery promise in minutes and whether it is critical."""
        with open_store(vault, read_only=True) as conn:
            return rows(
                conn,
                "MATCH (f:Function) RETURN f.name AS function, f.promise_min AS promise_min, f.critical AS critical "
                "ORDER BY function",
            )

    @server.tool()
    def check_promises(view: str = "evidence") -> dict[str, Any]:
        """Broken promises (a dependency recovers slower than the promise), restore chains longer than the promise,
        and the dependencies the plan's own list leaves out. view: plan, architecture or evidence."""
        v = _view(view)
        with open_store(vault, read_only=True) as conn:
            return {
                "view": v,
                "broken_promises": [f.to_dict() for f in checks.inversions(conn, v)],
                "restore_chains": [f.to_dict() for f in checks.restore_chains(conn, v)],
                "plan_gaps": checks.plan_gaps(conn, v) if v != "plan" else [],
            }

    @server.tool()
    def explain_function(function: str) -> dict[str, Any]:
        """One function in every view: its dependencies, slowest link and longest restore chain, with paths."""
        with open_store(vault, read_only=True) as conn:
            try:
                return {view: plain(checks.profile(conn, view, function)) for view in checks.VIEWS}
            except KeyError:
                return {"error": f"no function named {function!r}"}

    @server.tool()
    def what_if(notice: str, view: str = "evidence") -> dict[str, Any]:
        """Read an outage notice (free text): the components it names or describes, the expected outage, the
        functions it reaches, which promises break, and a restore order."""
        with open_store(vault, read_only=True) as conn:
            return whatif.what_if(conn, notice, view=_view(view)).to_dict()

    @server.tool()
    def check_new_call(
        source: str, target: str, functions: list[str] | None = None, mode: str = "sync"
    ) -> dict[str, Any]:
        """Before adding a call from one component to another: the promises it would break or make worse. Tried on an
        in-memory copy; the plan is not changed. functions: the functions the call serves (default: every function
        that reaches the source today)."""
        with open_store(vault, read_only=True) as conn:
            try:
                return guard.simulate_call(conn, source, target, functions, mode).to_dict()
            except ValueError as exc:
                return {"error": str(exc)}

    @server.tool()
    def get_schema() -> dict[str, Any]:
        """Labels with node counts, relationship types with counts, and the property names in use."""
        with open_store(vault, read_only=True) as conn:
            labels = rows(conn, "MATCH (n) UNWIND labels(n) AS label RETURN label, count(*) AS nodes ORDER BY label")
            types = rows(conn, "MATCH ()-[r]->() RETURN type(r) AS type, count(*) AS relationships ORDER BY type")
            keys = rows(
                conn,
                "MATCH (n) UNWIND labels(n) AS label UNWIND keys(n) AS key "
                "RETURN label, collect(DISTINCT key) AS properties ORDER BY label",
            )
            rel_keys = rows(
                conn,
                "MATCH ()-[r]->() UNWIND keys(r) AS key RETURN type(r) AS type, collect(DISTINCT key) AS properties",
            )
        return {
            "labels": labels,
            "relationship_types": types,
            "node_properties": keys,
            "relationship_properties": rel_keys,
        }

    @server.tool()
    def read_cypher(query: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run a read-only Cypher query on the plan (Relate refuses writes on a read-only open). Rows are capped at
        200."""
        with open_store(vault, read_only=True) as conn:
            try:
                cursor = conn.execute(query, params or {})
                result = [plain(dict(row)) for row in cursor.fetch(ROW_CAP + 1)]
            except relate.Error as exc:
                return {"error": str(exc)}
        return {"rows": result[:ROW_CAP], "truncated": len(result) > ROW_CAP}

    return server


def _view(view: str) -> checks.View:
    if view not in checks.VIEWS:
        raise ValueError(f"view is one of {', '.join(checks.VIEWS)}")
    return view


def run(vault: Path) -> None:
    build_server(vault).run("stdio")
