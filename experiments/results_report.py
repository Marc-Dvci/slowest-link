"""Write docs/RESULTS.md from the committed evidence, so every number in it comes from a file in evidence/.

python experiments/results_report.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from slowest_link import checks  # noqa: E402
from slowest_link.report import minutes  # noqa: E402
from slowest_link.store import open_store  # noqa: E402

EVIDENCE = ROOT / "evidence"
VIEW = {"plan": "Plan", "architecture": "Architecture", "evidence": "Evidence"}


def load(name: str) -> Any:
    path = EVIDENCE / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def pct(x: float | None) -> str:
    return "-" if x is None else f"{round(100 * x)}%"


def score_table(views: dict[str, Any]) -> list[str]:
    lines = [
        "| View | Outages predicted | False alarms | Precision | Recall | Tests exactly right |",
        "|---|---|---|---|---|---|",
    ]
    for view in checks.VIEWS:
        s = views[view]["score"]
        lines.append(
            f"| {VIEW[view]} | {s['tp']} of {s['tp'] + s['fn']} | {s['fp']} | {pct(s['precision'])} | "
            f"{pct(s['recall'])} | {s['exact']} of {s['tests']} |"
        )
    return lines


def outcome_table(results: dict[str, Any], predictions: dict[str, Any], kind: str) -> list[str]:
    by_id = {f["id"]: f for f in predictions["faults"]}
    head = "| Fault | Functions measured down | Plan | Architecture | Evidence |"
    lines = [head, "|---|---|---|---|---|"]
    for o in results["outcomes"]:
        if o["kind"] != kind:
            continue
        judged = [f for f in results["functions"] if f not in o["unjudged"]]
        measured = set(o["affected"])
        marks = []
        for view in checks.VIEWS:
            predicted = set(by_id[o["test"]]["predicted"][view]) & set(judged)
            wrong = (predicted ^ measured) & set(judged)
            marks.append("right" if not wrong else f"{len(wrong)} wrong")
        fault = o["test"].split(":", 1)[1]
        lines.append(f"| {fault} | {', '.join(sorted(measured)) or 'none'} | {' | '.join(marks)} |")
    return lines


def window(kind: str) -> str:
    """The fault windows of one kind of test, in seconds, as the timeline measured them."""
    path = EVIDENCE / "e1e2" / "timeline.jsonl"
    tests = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    spans = sorted({round(t["t_fault_end"] - t["t_fault"]) for t in tests if t["kind"] == kind})
    if not spans:
        return "a fixed window"
    return f"{spans[0]} seconds" if len(spans) == 1 else f"{spans[0]} to {spans[-1]} seconds"


def main() -> None:
    predictions = load("predictions.json")
    results = load("e1e2-results.json")
    observed = load("e0-observed-calls.json")
    agent = load("agent-eval/summary.json")
    with open_store(ROOT / "plan", read_only=True) as conn:
        found = {view: (checks.inversions(conn, view), checks.restore_chains(conn, view)) for view in checks.VIEWS}
        unseen = checks.unseen_calls(conn)
        hidden = checks.hidden_calls(conn)
        gaps = checks.plan_gaps(conn, "evidence")
        manual = checks.not_self_recovering(conn)

    out = ["# Results", "", "Every number on this page is computed from the files in [`evidence/`](../evidence/) and the plan",
           "vault by [`experiments/results_report.py`](../experiments/results_report.py).", ""]  # fmt: skip

    out += ["## Traces (E0)", ""]
    if observed:
        calls = observed["calls"]
        out += [
            f"- {observed['traces']} traces, {observed['attributed']} attributed to a function of the plan.",
            f"- {len(calls)} calls between components observed; {len(calls) - len(hidden)} of them are in the published "
            f"architecture and {len(hidden)} are not.",
            f"- {len(unseen)} declared calls appear in no trace: "
            + ", ".join(f"{u['source']} -> {u['target']}" for u in unseen)
            + ".",
            "",
        ]

    out += [
        "## Findings on the plan",
        "",
        "| View | Broken promises | Restore chains past the promise |",
        "|---|---|---|",
    ]
    for view in checks.VIEWS:
        inv, chains = found[view]
        out.append(
            f"| {VIEW[view]} | {len(inv)}: {', '.join(f.function for f in inv) or 'none'} | "
            f"{len(chains)}: {', '.join(f'{c.function} ({minutes(c.value_min)})' for c in chains) or 'none'} |"
        )
    out += ["", "Dependencies the plan's own list leaves out (evidence view):", ""]
    for g in gaps:
        out.append(
            f"- {g['function']}: " + ", ".join(f"{m['component']} ({minutes(m['recovery_min'])})" for m in g["missing"])
        )
    out.append("")

    if results and predictions:
        out += [
            "## Outage tests (E1 and E2)",
            "",
            "Predictions were committed before the tests ran. A pair is one fault and one function; back-office",
            "functions are left out of a test when no order was placed in its window.",
            "",
            f"### Stopping each component for {window('stop')} (E1)",
            "",
        ]
        out += score_table(results["views"]["stop"]) + [""]
        out += outcome_table(results, predictions, "stop") + [""]
        out += [f"### Turning on each failure flag for {window('flag')} (E2)", ""]
        out += score_table(results["views"]["flag"]) + [""]
        out += outcome_table(results, predictions, "flag") + [""]
        slow = [
            (o["target"], j, s)
            for o in results["outcomes"]
            if o["kind"] == "stop"
            for j, s in o["recovery_s"].items()
            if s is not None and o["journeys"].get(j, {}).get("affected")
        ]
        if slow:
            longest = max(slow, key=lambda x: x[2])
            out += [
                f"Measured recovery after a restart, over {len(slow)} affected journeys: longest "
                f"{longest[2]} s ({longest[1]} after {longest[0]}).",
                "",
            ]
        if manual:
            out += ["Stop tests that left a journey down until the services were restarted:", ""]
            out += [f"- {m['component']}: {', '.join(m['journeys'])}" for m in manual] + [""]

    if agent:
        out += [
            "## Agent evaluation",
            "",
            "| How the model answered | Correct | Tool calls | Prompt tokens |",
            "|---|---|---|---|",
        ]
        for mode, row in agent.items():
            label = "Reading the plan's notes" if mode == "files" else "With the Slowest Link tools on Relate"
            out.append(
                f"| {label} | {row['correct']} of {row['answers']} ({pct(row['share'])}) | {row['tool_calls']} | "
                f"{row['prompt_tokens']:,} |"
            )
        out.append("")

    (ROOT / "docs" / "RESULTS.md").write_text("\n".join(out), encoding="utf-8")
    print("wrote docs/RESULTS.md")


if __name__ == "__main__":
    main()
