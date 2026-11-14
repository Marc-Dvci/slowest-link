"""What-if: read an outage notice and list the promises it breaks, with a restore order.

1. Components: names written in the notice, then Relate's full-text `SEARCH` over component names and descriptions
   (hits scoring at least 60% of the best hit).
2. Duration: the first duration in the notice ("3 hours", "2 h 28 min", "90 minutes"); without one, each matched
   component's declared recovery objective.
3. Impact: every function whose dependencies in the chosen view include a matched component. A promise is broken
   when the expected outage is longer than the promise.
4. Restore order: matched components with their dependencies first, then functions by tightest promise.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import relate

from slowest_link import checks
from slowest_link.store import rows

RELATIVE_SCORE = 0.6
_WORD = re.compile(r"[a-z0-9][a-z0-9-]*")
_DURATION = re.compile(
    r"(?:(?P<h>\d+(?:\.\d+)?)\s*(?:h|hr|hrs|hour|hours)\b)?\s*(?:and\s*)?"
    r"(?:(?P<m>\d+)\s*(?:m|min|mins|minute|minutes)\b)?",
    re.IGNORECASE,
)


@dataclass
class WhatIf:
    notice: str
    view: str
    components: list[dict[str, Any]]
    outage_min: int | None
    affected: list[dict[str, Any]] = field(default_factory=list)
    restore_order: list[str] = field(default_factory=list)

    @property
    def broken(self) -> list[dict[str, Any]]:
        return [row for row in self.affected if row["broken"]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "view": self.view,
            "components": self.components,
            "outage_min": self.outage_min,
            "affected": self.affected,
            "broken": [row["function"] for row in self.broken],
            "restore_order": self.restore_order,
        }


def parse_duration(text: str) -> int | None:
    """The first duration in the text, in whole minutes, or None."""
    for match in _DURATION.finditer(text):
        hours, minutes = match.group("h"), match.group("m")
        if hours or minutes:
            return round(float(hours or 0) * 60 + int(minutes or 0))
    return None


def match_components(conn: relate.Connection, notice: str) -> list[dict[str, Any]]:
    """Components the notice is about: exact names first, then full-text hits close to the best one."""
    names = [row["n"] for row in rows(conn, f"MATCH (c:{checks.COMPONENT}) RETURN c.name AS n")]
    lowered = notice.lower()
    exact = [n for n in names if re.search(rf"(?<![a-z0-9-]){re.escape(n)}(?![a-z0-9-])", lowered)]
    found = [{"component": n, "how": "named", "score": None} for n in sorted(exact)]
    terms = " ".join(_WORD.findall(lowered))
    if terms:
        hits = rows(
            conn,
            "MATCH (n) SEARCH n IN (FULLTEXT INDEX component_text FOR $q LIMIT 5) SCORE AS score "
            "RETURN n.name AS component, score ORDER BY score DESC",
            {"q": terms},
        )
        if hits:
            top = float(hits[0]["score"])
            for hit in hits:
                if float(hit["score"]) >= RELATIVE_SCORE * top and hit["component"] not in exact:
                    found.append({"component": hit["component"], "how": "search", "score": round(float(hit["score"]), 3)})
    return found


def _dependency_first(conn: relate.Connection, components: list[str]) -> list[str]:
    """Order components so that each comes after the components it calls (declared or observed)."""
    edges = rows(
        conn,
        f"MATCH (a:{checks.COMPONENT})-[r:CALLS]->(b:{checks.COMPONENT}) "
        "WHERE a.name IN $names AND b.name IN $names AND (r.declared OR r.observed) "
        "RETURN a.name AS a, b.name AS b",
        {"names": components},
    )
    remaining = sorted(components)
    ordered: list[str] = []
    while remaining:
        ready = [c for c in remaining if not any(e["a"] == c and e["b"] in remaining and e["b"] != c for e in edges)]
        pick = ready[0] if ready else remaining[0]  # a cycle: break it by name
        ordered.append(pick)
        remaining.remove(pick)
    return ordered


def what_if(conn: relate.Connection, notice: str, view: checks.View = "evidence") -> WhatIf:
    matched = match_components(conn, notice)
    outage = parse_duration(notice)
    result = WhatIf(notice=notice, view=view, components=matched, outage_min=outage)
    if not matched:
        return result
    names = [m["component"] for m in matched]
    objectives = {
        row["n"]: int(row["r"])
        for row in rows(
            conn, f"MATCH (c:{checks.COMPONENT}) WHERE c.name IN $names RETURN c.name AS n, c.recovery_min AS r", {"names": names}
        )
    }
    reach = checks.reach(conn, view)
    functions = {
        row["name"]: row
        for row in rows(conn, "MATCH (f:Function) RETURN f.name AS name, f.promise_min AS promise, f.critical AS critical")
    }
    for name, deps in sorted(reach.items()):
        hit = sorted(set(names) & deps)
        if not hit:
            continue
        expected = outage if outage is not None else max(objectives[c] for c in hit)
        promise = int(functions[name]["promise"])
        result.affected.append(
            {
                "function": name,
                "promise_min": promise,
                "critical": bool(functions[name]["critical"]),
                "through": hit,
                "expected_outage_min": expected,
                "broken": expected > promise,
            }
        )
    result.affected.sort(key=lambda row: (not row["broken"], row["promise_min"], not row["critical"], row["function"]))
    result.restore_order = _dependency_first(conn, names) + [row["function"] for row in result.affected]
    return result
