"""The checks: deterministic Cypher over the plan graph.

Every number in a finding comes from a query result. A view decides which dependency edges count:

- plan: the components the plan lists for each function, one at a time (today's practice);
- architecture: the published architecture's declared calls, followed transitively from the function's entry point;
- evidence: calls observed in the function's own traces, synchronous only, minus calls a test proved the function
  survives without.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import relate

from slowest_link.store import rows

View = Literal["plan", "architecture", "evidence"]
VIEWS: tuple[View, ...] = ("plan", "architecture", "evidence")

COMPONENT = "Service|Datastore|Queue"

# Which CALLS edges a view follows. `f` is the function, `r` the edge. Constant strings, never user input.
EDGE_FILTER: dict[View, str] = {
    "architecture": "r.declared = true",
    "evidence": (
        "r.observed = true AND f.name IN coalesce(r.journeys, []) AND r.mode = 'sync' "
        "AND NOT coalesce(r.fallback, false)"
    ),
}

# Every path from a function's entry point through the edges a view follows (cycle-free).
_PATHS = """
MATCH (f:Function)-[:ENTERS]->(entry)
MATCH p = ACYCLIC (entry)-[rs:CALLS]->*(d)
WHERE all(r IN rs WHERE {edge_filter})
"""

# The plan view has no paths: each listed component counts on its own.
_PLAN_PATHS = """
MATCH (f:Function)-[:USES]->(d)
WITH f, d, [d.name] AS names, [] AS declared, d.recovery_min AS chain
"""


def _paths(view: View) -> str:
    """The MATCH that binds f (function), d (dependency), names (path), declared (per hop) and chain."""
    if view == "plan":
        return _PLAN_PATHS
    return _PATHS.format(edge_filter=EDGE_FILTER[view]) + (
        "WITH f, d, [n IN nodes(p) | n.name] AS names, [r IN rs | coalesce(r.declared, false)] AS declared, "
        "reduce(total = 0, n IN nodes(p) | total + n.recovery_min) AS chain\n"
    )


@dataclass(frozen=True)
class Finding:
    check: str
    view: View
    function: str
    promise_min: int
    value_min: int
    component: str
    path: list[str]
    hidden_hops: list[str] = field(default_factory=list)

    @property
    def gap_min(self) -> int:
        return self.value_min - self.promise_min

    def to_dict(self) -> dict[str, Any]:
        return {
            "check": self.check,
            "view": self.view,
            "function": self.function,
            "promise_min": self.promise_min,
            "value_min": self.value_min,
            "gap_min": self.gap_min,
            "component": self.component,
            "path": self.path,
            "hidden_hops": self.hidden_hops,
        }


def _hidden_hops(names: list[str], declared: list[bool]) -> list[str]:
    return [f"{names[i]} -> {names[i + 1]}" for i, ok in enumerate(declared) if not ok]


def inversions(conn: relate.Connection, view: View) -> list[Finding]:
    """Functions whose promise is shorter than the slowest recovery objective among their dependencies."""
    query = _paths(view) + """
WITH f, d, names, declared ORDER BY d.recovery_min DESC, size(names) ASC, d.name ASC
WITH f, collect({component: d.name, recovery: d.recovery_min, names: names, declared: declared})[0] AS slowest
WHERE slowest.recovery > f.promise_min
RETURN f.name AS function, f.promise_min AS promise, slowest.component AS component, slowest.recovery AS value,
       slowest.names AS names, slowest.declared AS declared
ORDER BY function
"""
    return [_finding("inversion", view, row) for row in rows(conn, query)]


def restore_chains(conn: relate.Connection, view: View) -> list[Finding]:
    """Functions whose promise is shorter than their longest restore chain.

    A dependent cannot be restored before what it depends on, so the time to bring a function back after losing
    everything is the longest path of recovery objectives under it (its critical path).
    """
    query = _paths(view) + """
WITH f, d, names, declared, chain ORDER BY chain DESC, size(names) ASC, d.name ASC
WITH f, collect({component: d.name, chain: chain, names: names, declared: declared})[0] AS longest
WHERE longest.chain > f.promise_min
RETURN f.name AS function, f.promise_min AS promise, longest.component AS component, longest.chain AS value,
       longest.names AS names, longest.declared AS declared
ORDER BY function
"""
    return [_finding("restore_chain", view, row) for row in rows(conn, query)]


def _finding(check: str, view: View, row: dict[str, Any]) -> Finding:
    names = list(row["names"])
    return Finding(
        check=check,
        view=view,
        function=row["function"],
        promise_min=int(row["promise"]),
        value_min=int(row["value"]),
        component=row["component"],
        path=names,
        hidden_hops=_hidden_hops(names, list(row["declared"])),
    )


def reach(conn: relate.Connection, view: View) -> dict[str, set[str]]:
    """Each function's dependency set in a view (the components whose loss can stop it)."""
    query = _paths(view) + "RETURN f.name AS function, collect(DISTINCT d.name) AS components"
    result = {row["function"]: set(row["components"]) for row in rows(conn, query)}
    for row in rows(conn, "MATCH (f:Function) RETURN f.name AS function"):
        result.setdefault(row["function"], set())
    return result


def profile(conn: relate.Connection, view: View, function: str) -> dict[str, Any]:
    """One function in one view: its dependencies, its slowest link and its longest restore chain, with paths."""
    query = _paths(view) + """
WITH f, d, names, declared, chain WHERE f.name = $function
WITH f, collect({component: d.name, recovery: d.recovery_min, chain: chain, names: names, declared: declared}) AS all
RETURN f.name AS function, f.promise_min AS promise,
       [x IN all | x.component] AS components,
       reduce(best = null, x IN all | CASE WHEN best IS NULL OR x.recovery > best.recovery
              OR (x.recovery = best.recovery AND size(x.names) < size(best.names)) THEN x ELSE best END) AS slowest,
       reduce(best = null, x IN all | CASE WHEN best IS NULL OR x.chain > best.chain
              OR (x.chain = best.chain AND size(x.names) < size(best.names)) THEN x ELSE best END) AS longest
"""
    found = rows(conn, query, {"function": function})
    if not found:
        known = rows(conn, "MATCH (f:Function {name: $function}) RETURN f.promise_min AS promise", {"function": function})
        if not known:
            raise KeyError(function)
        return {"function": function, "promise": known[0]["promise"], "components": [], "slowest": None, "longest": None}
    row = found[0]
    row["components"] = sorted(set(row["components"]))
    for key in ("slowest", "longest"):
        if row[key] is not None:
            row[key] = {**row[key], "hidden_hops": _hidden_hops(list(row[key]["names"]), list(row[key]["declared"]))}
    return row


def plan_gaps(conn: relate.Connection, view: View = "evidence") -> list[dict[str, Any]]:
    """Components a function depends on that the plan's own list for it leaves out, with the slowest first."""
    query = _paths(view) + f"""
WITH f, d WHERE (d:{COMPONENT}) AND NOT EXISTS {{ MATCH (f)-[:USES]->(d) }}
WITH f, d ORDER BY d.recovery_min DESC, d.name
WITH f, collect(DISTINCT {{component: d.name, recovery_min: d.recovery_min}}) AS missing
RETURN f.name AS function, f.promise_min AS promise_min, missing
ORDER BY function
"""
    return rows(conn, query)


def hidden_calls(conn: relate.Connection) -> list[dict[str, Any]]:
    """Calls seen in traces that neither the plan nor the published architecture declares."""
    query = f"""
MATCH (a:{COMPONENT})-[r:CALLS]->(b:{COMPONENT})
WHERE r.observed = true AND NOT coalesce(r.declared, false)
RETURN a.name AS source, b.name AS target, r.mode AS mode, coalesce(r.journeys, []) AS journeys,
       coalesce(r.calls, 0) AS calls
ORDER BY source, target
"""
    return rows(conn, query)


def unseen_calls(conn: relate.Connection) -> list[dict[str, Any]]:
    """Declared calls that no trace showed: the plan may describe a call the system no longer makes."""
    query = f"""
MATCH (a:{COMPONENT})-[r:CALLS]->(b:{COMPONENT})
WHERE r.declared = true AND NOT coalesce(r.observed, false)
RETURN a.name AS source, b.name AS target, r.protocol AS protocol
ORDER BY source, target
"""
    return rows(conn, query)


def untested_components(conn: relate.Connection, view: View, since: str) -> list[dict[str, Any]]:
    """Components under a critical function that no recovery test exercised on or after `since` (YYYY-MM-DD)."""
    query = _paths(view) + f"""
WITH f, d WHERE f.critical = true AND (d:{COMPONENT})
WITH d, collect(DISTINCT f.name) AS functions
WHERE NOT EXISTS {{ MATCH (t:Test)-[:EXERCISED]->(d) WHERE t.date >= $since }}
RETURN d.name AS component, d.recovery_min AS recovery_min, functions
ORDER BY size(functions) DESC, component
"""
    return rows(conn, query, {"since": since})


def shared_points(conn: relate.Connection, view: View, minimum: int = 2) -> list[dict[str, Any]]:
    """Components that two or more critical functions depend on: one loss, several broken promises."""
    query = _paths(view) + f"""
WITH f, d WHERE f.critical = true AND (d:{COMPONENT})
WITH d, collect(DISTINCT f.name) AS functions
WHERE size(functions) >= $minimum
RETURN d.name AS component, d.recovery_min AS recovery_min, functions
ORDER BY size(functions) DESC, recovery_min DESC, component
"""
    return rows(conn, query, {"minimum": minimum})


def not_self_recovering(conn: relate.Connection) -> list[dict[str, Any]]:
    """Components whose stop test left a journey down until someone acted: the plan needs a manual step."""
    query = """
MATCH (t:Test)-[:EXERCISED]->(c)
WHERE t.kind = 'stop' AND size(coalesce(t.not_recovered, [])) > 0
RETURN c.name AS component, t.name AS test, t.date AS date, t.not_recovered AS journeys
ORDER BY component
"""
    return rows(conn, query)


def run_all(conn: relate.Connection, since: str) -> dict[str, Any]:
    """Every check in every view, as plain data for reports, CI and agents."""
    return {
        "inversions": {view: [f.to_dict() for f in inversions(conn, view)] for view in VIEWS},
        "restore_chains": {view: [f.to_dict() for f in restore_chains(conn, view)] for view in VIEWS},
        "plan_gaps": plan_gaps(conn, "evidence"),
        "hidden_calls": hidden_calls(conn),
        "unseen_calls": unseen_calls(conn),
        "untested_components": untested_components(conn, "evidence", since),
        "shared_points": shared_points(conn, "evidence"),
        "not_self_recovering": not_self_recovering(conn),
    }
