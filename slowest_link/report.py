"""Plain-text reports for the terminal, CI logs and agents. Every number comes from a check's result."""

from __future__ import annotations

from typing import Any

import relate

from slowest_link import checks
from slowest_link.guard import GuardResult
from slowest_link.whatif import WhatIf

VIEW_LABEL = {
    "plan": "Plan (each listed component on its own)",
    "architecture": "Architecture (published calls, followed through)",
    "evidence": "Evidence (calls seen in each function's own traces)",
}


def minutes(value: int | float | None) -> str:
    if value is None:
        return "-"
    value = int(value)
    hours, mins = divmod(value, 60)
    if not hours:
        return f"{mins} min"
    return f"{hours} h" if not mins else f"{hours} h {mins:02d} min"


def path_text(names: list[str], hidden_hops: list[str] | None = None) -> str:
    hidden = set(hidden_hops or [])
    parts = [names[0]] if names else []
    for a, b in zip(names, names[1:], strict=False):
        arrow = " ~> " if f"{a} -> {b}" in hidden else " -> "
        parts.append(arrow + b)
    return "".join(parts)


def _findings(title: str, by_view: dict[str, list[dict[str, Any]]], what: str) -> list[str]:
    lines = [title, ""]
    for view in checks.VIEWS:
        items = by_view[view]
        lines.append(f"  {VIEW_LABEL[view]}: {len(items)}")
        for f in items:
            lines.append(
                f"    {f['function']}: promises {minutes(f['promise_min'])}, {what} {minutes(f['value_min'])} "
                f"({minutes(f['gap_min'])} over)"
            )
            lines.append(f"      {path_text(f['path'], f['hidden_hops'])}")
    lines.append("")
    return lines


def render_check(result: dict[str, Any], as_of: str) -> str:
    lines = [f"Slowest Link check, as of {as_of}", ""]
    lines += _findings("Broken promises: a dependency recovers slower than the function promises", result["inversions"], "slowest link")
    lines += _findings("Restore chains longer than the promise (dependencies come back first)", result["restore_chains"], "chain")

    gaps = result["plan_gaps"]
    lines.append(f"Dependencies the plan's list leaves out, per function: {sum(len(g['missing']) for g in gaps)}")
    for g in gaps:
        missing = ", ".join(f"{m['component']} ({minutes(m['recovery_min'])})" for m in g["missing"])
        lines.append(f"  {g['function']} (promises {minutes(g['promise_min'])}): {missing}")
    lines.append("")
    hidden = result["hidden_calls"]
    lines.append(f"Calls seen in traces that the plan does not declare: {len(hidden)}")
    for h in hidden:
        lines.append(f"  {h['source']} ~> {h['target']} ({h['mode']}, {h['calls']} calls; {', '.join(h['journeys'])})")
    lines.append("")
    unseen = result["unseen_calls"]
    lines.append(f"Declared calls no trace showed: {len(unseen)}")
    for u in unseen:
        lines.append(f"  {u['source']} -> {u['target']}")
    lines.append("")
    untested = result["untested_components"]
    lines.append(f"Components under a critical function with no recovery test in the last 365 days: {len(untested)}")
    for u in untested:
        lines.append(f"  {u['component']} (recovers in {minutes(u['recovery_min'])}; under {', '.join(u['functions'])})")
    lines.append("")
    shared = result["shared_points"]
    lines.append(f"Shared points under two or more critical functions: {len(shared)}")
    for s in shared:
        lines.append(f"  {s['component']}: {len(s['functions'])} functions ({', '.join(s['functions'])})")
    lines.append("")
    manual = result["not_self_recovering"]
    lines.append(f"Components whose stop test left a journey down until someone acted: {len(manual)}")
    for m in manual:
        lines.append(f"  {m['component']} ({m['date']}): {', '.join(m['journeys'])}")
    lines.append("")
    lines.append("~> marks a call seen in traces that the plan does not declare.")
    return "\n".join(lines)


def render_explain(conn: relate.Connection, function: str) -> str:
    lines: list[str] = []
    for view in checks.VIEWS:
        p = checks.profile(conn, view, function)
        if not lines:
            lines += [f"{function}: promises {minutes(p['promise'])}", ""]
        lines.append(VIEW_LABEL[view])
        lines.append(f"  depends on {len(p['components'])}: {', '.join(p['components']) or '-'}")
        slow, chain = p["slowest"], p["longest"]
        if slow:
            mark = "BROKEN" if slow["recovery"] > p["promise"] else "ok"
            lines.append(f"  slowest link: {slow['component']}, {minutes(slow['recovery'])} [{mark}]")
            lines.append(f"    {path_text(slow['names'], slow['hidden_hops'])}")
        if chain:
            mark = "BROKEN" if chain["chain"] > p["promise"] else "ok"
            lines.append(f"  restore chain: {minutes(chain['chain'])} [{mark}]")
            lines.append(f"    {path_text(chain['names'], chain['hidden_hops'])}")
        lines.append("")
    return "\n".join(lines)


def render_whatif(result: WhatIf) -> str:
    if not result.components:
        return "No component of the plan matches this notice."
    lines = ["Components in the notice:"]
    for c in result.components:
        how = "named" if c["how"] == "named" else f"search score {c['score']}"
        lines.append(f"  {c['component']} ({how})")
    outage = minutes(result.outage_min) if result.outage_min is not None else "not stated; using recovery objectives"
    lines += ["", f"Expected outage: {outage}", "", f"Functions reached ({VIEW_LABEL[result.view]}):"]
    for row in result.affected:
        state = "BROKEN" if row["broken"] else "kept"
        lines.append(
            f"  [{state}] {row['function']}: promises {minutes(row['promise_min'])}, "
            f"out {minutes(row['expected_outage_min'])} (through {', '.join(row['through'])})"
        )
    if not result.affected:
        lines.append("  none")
    lines += ["", "Restore order: " + " -> ".join(result.restore_order)]
    return "\n".join(lines)


def render_guard(result: GuardResult) -> str:
    lines = [f"Change: {result.change}"]
    if not result.blocking:
        lines.append("No promise breaks or gets worse.")
        return "\n".join(lines)
    for f in result.new:
        what = "slowest link" if f["check"] == "inversion" else "restore chain"
        lines.append(f"NEW    {f['function']}: promises {minutes(f['promise_min'])}, {what} {minutes(f['value_min'])}")
        lines.append(f"       {path_text(f['path'], f['hidden_hops'])}")
    for f in result.worse:
        what = "slowest link" if f["check"] == "inversion" else "restore chain"
        lines.append(
            f"WORSE  {f['function']}: promises {minutes(f['promise_min'])}, "
            f"{what} {minutes(f['was_min'])} -> {minutes(f['value_min'])}"
        )
        lines.append(f"       {path_text(f['path'], f['hidden_hops'])}")
    return "\n".join(lines)
