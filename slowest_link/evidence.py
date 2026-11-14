"""Write evidence into the plan: calls observed in traces, and the results of recovery tests.

Evidence never overwrites what people declared. An observed call sets `observed`, `mode`, `journeys` and `calls` on
the declared edge it confirms, or adds a new edge marked `declared: false` (a hidden dependency). A test adds a
`Test` note linked to the component it exercised.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

import relate

from slowest_link.store import rows
from slowest_link.traces import Derivation, ObservedCall

COMPONENT = "Service|Datastore|Queue"


def plan_maps(conn: relate.Connection) -> tuple[dict[str, str], dict[str, str], set[str]]:
    """journey -> function, consumer component -> function, and the set of component names."""
    journey_to_function: dict[str, str] = {}
    consumer_function: dict[str, str] = {}
    for row in rows(conn, "MATCH (f:Function)-[:ENTERS]->(e) RETURN f.name AS f, f.journeys AS j, e.name AS e"):
        for journey in row["j"] or []:
            journey_to_function[journey] = row["f"]
        if not row["j"]:
            consumer_function[row["e"]] = row["f"]
    components = {row["n"] for row in rows(conn, f"MATCH (c:{COMPONENT}) RETURN c.name AS n")}
    return journey_to_function, consumer_function, components


def apply_observed(conn: relate.Connection, calls: Iterable[ObservedCall], observed_on: str) -> dict[str, int]:
    """Replace the previous trace evidence with these observed calls. Returns counts of confirmed and new edges."""
    calls = list(calls)
    known = {row["n"] for row in rows(conn, f"MATCH (c:{COMPONENT}) RETURN c.name AS n")}
    unknown = sorted({name for call in calls for name in (call.source, call.target)} - known)
    if unknown:
        raise ValueError(f"observed calls name components the plan does not have: {unknown}")

    conn.autocommit = False
    conn.execute("MATCH ()-[r:CALLS]->() WHERE NOT coalesce(r.declared, false) AND r.source = 'traces' DELETE r")
    conn.execute(
        "MATCH ()-[r:CALLS]->() WHERE r.observed = true "
        "SET r.observed = false, r.journeys = [], r.calls = 0, r.mode = 'unknown' REMOVE r.observed_on"
    )
    confirmed = added = 0
    for call in calls:
        existing = rows(
            conn,
            f"MATCH (a:{COMPONENT} {{name: $s}})-[r:CALLS]->(b:{COMPONENT} {{name: $t}}) RETURN count(r) AS n",
            {"s": call.source, "t": call.target},
        )[0]["n"]
        params: dict[str, Any] = {
            "s": call.source,
            "t": call.target,
            "mode": call.mode,
            "journeys": sorted(call.journeys),
            "calls": call.calls,
            "on": observed_on,
        }
        if existing:
            conn.execute(
                f"MATCH (a:{COMPONENT} {{name: $s}})-[r:CALLS]->(b:{COMPONENT} {{name: $t}}) "
                "SET r.observed = true, r.mode = $mode, r.journeys = $journeys, r.calls = $calls, r.observed_on = $on",
                params,
            )
            confirmed += 1
        else:
            conn.execute(
                f"MATCH (a:{COMPONENT} {{name: $s}}), (b:{COMPONENT} {{name: $t}}) "
                "CREATE (a)-[:CALLS {declared: false, observed: true, mode: $mode, journeys: $journeys, "
                "calls: $calls, observed_on: $on, source: 'traces'}]->(b)",
                params,
            )
            added += 1
    conn.commit()
    conn.autocommit = True
    return {"confirmed": confirmed, "added": added}


def import_derivation(conn: relate.Connection, derivation: Derivation, observed_on: str) -> dict[str, int]:
    counts = apply_observed(conn, derivation.calls, observed_on)
    return {"traces": derivation.traces, "attributed": derivation.attributed, **counts}


def record_test(conn: relate.Connection, test: Mapping[str, Any]) -> None:
    """Add one recovery test result: a `Test` note linked to the component it exercised.

    Required keys: name, date (YYYY-MM-DD), kind ("stop" or "flag"), target (component name).
    Optional: fault, window_s, affected (journeys), recovery_s (journey -> seconds), not_recovered (journeys).
    """
    for key in ("name", "date", "kind", "target"):
        if key not in test:
            raise ValueError(f"a test needs {key!r}")
    target_exists = rows(conn, f"MATCH (c:{COMPONENT} {{name: $t}}) RETURN count(c) AS n", {"t": test["target"]})
    if not target_exists[0]["n"]:
        raise ValueError(f"no component named {test['target']!r}")
    recovery = dict(test.get("recovery_s") or {})
    conn.execute(
        f"MATCH (c:{COMPONENT} {{name: $target}}) "
        "MERGE (t:Test {name: $name}) "
        "SET t.date = $date, t.kind = $kind, t.fault = $fault, t.window_s = $window, t.affected = $affected, "
        "t.not_recovered = $not_recovered, t.recovery_journeys = $rj, t.recovery_s = $rs "
        "MERGE (t)-[:EXERCISED]->(c)",
        {
            "target": test["target"],
            "name": test["name"],
            "date": test["date"],
            "kind": test["kind"],
            "fault": test.get("fault", test["kind"]),
            "window": int(test.get("window_s", 0)),
            "affected": sorted(test.get("affected") or []),
            "not_recovered": sorted(test.get("not_recovered") or []),
            "rj": sorted(recovery),
            "rs": [float(recovery[k]) for k in sorted(recovery)],
        },
    )


def record_survival(conn: relate.Connection, function: str, component: str, test: str) -> int:
    """Mark the calls into `component` on `function`'s traced paths as calls the function survived without.

    Called when a stop test of `component` left `function` working. Returns the number of edges marked.
    """
    edges = rows(
        conn,
        f"MATCH (a:{COMPONENT})-[r:CALLS]->(b:{COMPONENT} {{name: $c}}) "
        "WHERE r.observed = true AND $f IN coalesce(r.journeys, []) AND NOT $f IN coalesce(r.survives_without, []) "
        "SET r.survives_without = coalesce(r.survives_without, []) + $f, "
        "    r.survival_tests = coalesce(r.survival_tests, []) + $t "
        "RETURN count(r) AS n",
        {"c": component, "f": function, "t": test},
    )
    return int(edges[0]["n"])


def record_need(conn: relate.Connection, function: str, component: str, test: str) -> int:
    """Mark the calls into `component` on `function`'s traced paths as calls the function needs.

    Called when a stop test of `component` stopped `function` although the evidence view did not reach it, for
    example a call that traces show as asynchronous. Returns the number of edges marked.
    """
    edges = rows(
        conn,
        f"MATCH (a:{COMPONENT})-[r:CALLS]->(b:{COMPONENT} {{name: $c}}) "
        "WHERE r.observed = true AND $f IN coalesce(r.journeys, []) AND NOT $f IN coalesce(r.needed_by, []) "
        "SET r.needed_by = coalesce(r.needed_by, []) + $f, "
        "    r.need_tests = coalesce(r.need_tests, []) + $t "
        "RETURN count(r) AS n",
        {"c": component, "f": function, "t": test},
    )
    return int(edges[0]["n"])
