"""The guard: before a change merges, say which promises it would break.

Two ways in:

- `simulate_call`: a new call between two components, tried on an in-memory copy of the plan;
- `compare`: two versions of the plan (the base branch and the change), as CI sees them.

Only findings that are new, or worse than before, are reported.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import relate

from slowest_link import checks
from slowest_link.export import copy_to_memory
from slowest_link.store import rows


@dataclass
class GuardResult:
    change: str
    new: list[dict[str, Any]] = field(default_factory=list)
    worse: list[dict[str, Any]] = field(default_factory=list)

    @property
    def blocking(self) -> bool:
        return bool(self.new or self.worse)

    def to_dict(self) -> dict[str, Any]:
        return {"change": self.change, "blocking": self.blocking, "new": self.new, "worse": self.worse}


def findings(conn: relate.Connection, view: checks.View) -> dict[tuple[str, str], dict[str, Any]]:
    """Broken promises and over-long restore chains in one view, keyed by (check, function)."""
    found = checks.inversions(conn, view) + checks.restore_chains(conn, view)
    return {(f.check, f.function): f.to_dict() for f in found}


def diff(before: relate.Connection, after: relate.Connection, view: checks.View, change: str) -> GuardResult:
    old, new = findings(before, view), findings(after, view)
    result = GuardResult(change=change)
    for key, finding in sorted(new.items()):
        if key not in old:
            result.new.append(finding)
        elif finding["value_min"] > old[key]["value_min"]:
            result.worse.append({**finding, "was_min": old[key]["value_min"]})
    return result


def functions_through(conn: relate.Connection, component: str, view: checks.View = "evidence") -> list[str]:
    """Functions whose dependencies include `component` in a view: the ones a new call from it could serve."""
    return sorted(name for name, deps in checks.reach(conn, view).items() if component in deps)


def simulate_call(
    conn: relate.Connection,
    source: str,
    target: str,
    functions: list[str] | None = None,
    mode: str = "sync",
    view: checks.View = "evidence",
) -> GuardResult:
    """Add `source -> target` to an in-memory copy, as declared and observed for `functions`, and diff the view.

    Without `functions`, the call is assumed to serve every function that reaches `source` today.
    """
    names = {row["n"] for row in rows(conn, f"MATCH (c:{checks.COMPONENT}) RETURN c.name AS n")}
    for name in (source, target):
        if name not in names:
            raise ValueError(f"no component named {name!r}")
    if mode not in {"sync", "async"}:
        raise ValueError("mode is sync or async")
    served = functions if functions is not None else functions_through(conn, source, view)
    known = {row["n"] for row in rows(conn, "MATCH (f:Function) RETURN f.name AS n")}
    unknown = sorted(set(served) - known)
    if unknown:
        raise ValueError(f"no function named {unknown}")
    after = copy_to_memory(conn)
    try:
        existing = rows(
            after,
            f"MATCH (:{checks.COMPONENT} {{name: $s}})-[r:CALLS]->(:{checks.COMPONENT} {{name: $t}}) RETURN count(r) AS n",
            {"s": source, "t": target},
        )[0]["n"]
        if existing:
            after.execute(
                f"MATCH (:{checks.COMPONENT} {{name: $s}})-[r:CALLS]->(:{checks.COMPONENT} {{name: $t}}) "
                "SET r.declared = true, r.observed = true, r.mode = $mode, "
                "r.journeys = coalesce(r.journeys, []) + [f IN $fns WHERE NOT f IN coalesce(r.journeys, [])]",
                {"s": source, "t": target, "mode": mode, "fns": served},
            )
        else:
            after.execute(
                f"MATCH (a:{checks.COMPONENT} {{name: $s}}), (b:{checks.COMPONENT} {{name: $t}}) "
                "CREATE (a)-[:CALLS {declared: true, observed: true, mode: $mode, journeys: $fns, source: 'guard'}]->(b)",
                {"s": source, "t": target, "mode": mode, "fns": served},
            )
        if mode == "sync":
            # Requests that now reach the target will use its own synchronous calls too: extend the served functions
            # down every observed synchronous path below it.
            after.execute(
                f"MATCH (b:{checks.COMPONENT} {{name: $t}}) "
                "MATCH p = ACYCLIC (b)-[rs:CALLS]->*(x) "
                "WHERE all(r IN rs WHERE r.observed = true AND r.mode = 'sync') "
                "UNWIND rs AS r WITH DISTINCT r "
                "SET r.journeys = coalesce(r.journeys, []) + [f IN $fns WHERE NOT f IN coalesce(r.journeys, [])]",
                {"t": target, "fns": served},
            )
        change = f"{source} -> {target} ({mode}) for {', '.join(served) or 'no function'}"
        return diff(conn, after, view, change)
    finally:
        after.close()


def compare(base: relate.Connection, head: relate.Connection, view: checks.View = "evidence") -> GuardResult:
    """What a change to the plan breaks: findings in `head` that `base` does not have, or has smaller."""
    return diff(base, head, view, "plan change")
