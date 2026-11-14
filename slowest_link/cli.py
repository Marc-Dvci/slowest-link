"""Command line: `python -m slowest_link <command>`.

seed           build the plan vault from sources/
import-traces  add the calls seen in exported traces to the plan
check          run every check and print the findings
explain        show one function's dependencies, slowest link and restore chain in each view
whatif         read an outage notice and list the promises it breaks, with a restore order
predict        list, for each fault, the functions each view expects it to reach
score          compare the outage tests' measured effects with the frozen predictions
record-tests   write the outage tests into the plan, with the calls each function survived without
guard          say which promises a new call, or a change to the plan, would break
export         write the plan graph as one Cypher script (for the browser page)
mcp            serve the checks to agents over MCP (stdio)
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import io
import json
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any

from slowest_link import checks, guard, report, scoring, whatif
from slowest_link.evidence import import_derivation, plan_maps, record_need, record_survival, record_test
from slowest_link.export import export_cypher
from slowest_link.seed import seed
from slowest_link.store import open_store
from slowest_link.traces import derive_calls

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VAULT = ROOT / "plan"


def _since(as_of: str) -> str:
    return (dt.date.fromisoformat(as_of) - dt.timedelta(days=365)).isoformat()


def load_traces(folder: Path) -> list[dict[str, Any]]:
    traces: list[dict[str, Any]] = []
    for path in sorted(folder.glob("*.json.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            traces.extend(json.load(handle)["data"])
    seen: set[str] = set()
    unique = []
    for trace in traces:  # one trace can match two queries (a journey and a consumer)
        if trace["traceID"] not in seen:
            seen.add(trace["traceID"])
            unique.append(trace)
    return unique


def cmd_seed(a: argparse.Namespace) -> int:
    counts = seed(a.vault, a.sources)
    print(json.dumps(counts))
    return 0


def cmd_import_traces(a: argparse.Namespace) -> int:
    traces = load_traces(a.traces)
    with open_store(a.vault) as conn:
        journey_to_function, consumer_function, components = plan_maps(conn)
        derivation = derive_calls(traces, journey_to_function, consumer_function, components)
        counts = import_derivation(conn, derivation, a.date)
    if a.summary:
        a.summary.write_text(json.dumps(derivation.to_dict(), indent=2) + "\n", encoding="utf-8")
    print(json.dumps(counts))
    return 0


def cmd_check(a: argparse.Namespace) -> int:
    with open_store(a.vault, read_only=True) as conn:
        result = checks.run_all(conn, _since(a.as_of))
    if a.json:
        print(json.dumps(result, indent=2))
    else:
        print(report.render_check(result, a.as_of))
    if a.fail_on_inversion and result["inversions"][a.fail_view]:
        return 1
    return 0


def cmd_explain(a: argparse.Namespace) -> int:
    with open_store(a.vault, read_only=True) as conn:
        text = report.render_explain(conn, a.function)
    print(text)
    return 0


def cmd_whatif(a: argparse.Namespace) -> int:
    notice = a.notice if a.notice != "-" else sys.stdin.read()
    with open_store(a.vault, read_only=True) as conn:
        result = whatif.what_if(conn, notice, view=a.view)
    print(json.dumps(result.to_dict(), indent=2) if a.json else report.render_whatif(result))
    return 0


def cmd_predict(a: argparse.Namespace) -> int:
    with open_store(a.vault, read_only=True) as conn:
        reach = {view: checks.reach(conn, view) for view in checks.VIEWS}
        components = sorted(row["n"] for row in conn.execute("MATCH (c:Service|Datastore|Queue) RETURN c.name AS n"))
    with a.flags.open(encoding="utf-8", newline="") as handle:
        flags = list(csv.DictReader(handle))
    faults = [{"id": f"stop:{c}", "kind": "stop", "target": c} for c in components]
    faults += [{"id": f"flag:{f['flag']}", "kind": "flag", "target": f["target"]} for f in flags]
    predictions = []
    for fault in faults:
        predicted = {
            view: sorted(fn for fn, deps in reach[view].items() if fault["target"] in deps) for view in checks.VIEWS
        }
        predictions.append({**fault, "predicted": predicted})
    out = {"vault_commit": a.commit, "functions": sorted(reach["plan"]), "faults": predictions}
    a.out.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(f"{len(predictions)} faults x {len(checks.VIEWS)} views -> {a.out}")
    return 0


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def load_run(run: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, dict[str, Any]]]:
    probe = run / "probe.jsonl.gz" if (run / "probe.jsonl.gz").exists() else run / "probe.jsonl"
    records = _read_jsonl(probe)
    timeline = _read_jsonl(run / "timeline.jsonl")
    backoffice = {row["test"]: row for row in _read_jsonl(run / "backoffice.jsonl")}
    return records, timeline, backoffice


def outcomes_for(conn: Any, run: Path) -> tuple[list[scoring.TestOutcome], list[str]]:
    journey_to_function, consumer_function, _ = plan_maps(conn)
    journeys = {j: f for j, f in journey_to_function.items() if j in PROBED}
    backoffice = {"ledger": consumer_function["accounting"], "fraud": consumer_function["fraud-detection"]}
    records, timeline, rows_ = load_run(run)
    outcomes = [scoring.outcome(t, records, rows_.get(t["test"]), journeys, backoffice) for t in timeline]
    functions = sorted(set(journeys.values()) | set(backoffice.values()))
    return outcomes, functions


# The journeys the prober replays: one per function of the plan (experiments/prober.py).
PROBED = {
    "user_index",
    "user_browse_product",
    "user_get_recommendations",
    "user_get_ads",
    "user_view_cart",
    "user_add_to_cart",
    "user_checkout_single",
}


def cmd_score(a: argparse.Namespace) -> int:
    predictions = json.loads(a.predictions.read_text(encoding="utf-8"))
    with open_store(a.vault, read_only=True) as conn:
        outcomes, functions = outcomes_for(conn, a.run_dir)
    by_test = {f["id"]: f for f in predictions["faults"]}
    result: dict[str, Any] = {"functions": functions, "views": {}, "outcomes": [o.to_dict() for o in outcomes]}
    for kind in ("stop", "flag"):
        chosen = [o for o in outcomes if o.kind == kind]
        for view in checks.VIEWS:
            predicted = {o.test: by_test[o.test]["predicted"][view] for o in chosen}
            result["views"].setdefault(kind, {})[view] = {
                "score": scoring.score(chosen, predicted, functions).to_dict(),
                "errors": scoring.errors(chosen, predicted, functions),
            }
    a.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    for kind, views in result["views"].items():
        for view, data in views.items():
            s = data["score"]
            print(
                f"{kind:4} {view:12} tp={s['tp']:3} fp={s['fp']:3} fn={s['fn']:3} tn={s['tn']:3} "
                f"precision={s['precision']} recall={s['recall']} exact={s['exact']}/{s['tests']}"
            )
    return 0


def cmd_record_tests(a: argparse.Namespace) -> int:
    with open_store(a.vault) as conn:
        outcomes, functions = outcomes_for(conn, a.run_dir)
        windows = {t["test"]: round(float(t["t_fault_end"]) - float(t["t_fault"])) for t in load_run(a.run_dir)[1]}
        reach = checks.reach(conn, "evidence")
        written = survived = needed = 0
        for o in outcomes:
            record_test(
                conn,
                {
                    "name": f"{a.date} {o.test}",
                    "date": a.date,
                    "kind": o.kind,
                    "target": o.target,
                    "fault": o.test.split(":", 1)[1],
                    "window_s": windows.get(o.test, 0),
                    "affected": sorted(o.affected),
                    "recovery_s": {j: v for j, v in o.recovery_s.items() if v is not None},
                    "not_recovered": o.not_recovered if o.kind == "stop" else [],
                },
            )
            written += 1
            if o.kind != "stop":
                continue
            for function in functions:
                if function in o.unjudged:
                    continue
                reached = o.target in reach.get(function, set())
                if reached and function not in o.affected:
                    survived += record_survival(conn, function, o.target, f"{a.date} {o.test}")
                elif function in o.affected and not reached:
                    needed += record_need(conn, function, o.target, f"{a.date} {o.test}")
    print(json.dumps({"tests": written, "calls_marked_survivable": survived, "calls_marked_needed": needed}))
    return 0


def extract_plan(ref: str, folder: Path, vault: Path) -> Path:
    """Write the vault as it is at git `ref` into `folder` and return its path there."""
    rel = vault.resolve().relative_to(ROOT).as_posix()
    archive = subprocess.run(
        ["git", "-C", str(ROOT), "archive", "--format=tar", ref, rel], capture_output=True, check=True
    ).stdout
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(folder, filter="data")
    return folder / rel


def _hook_wants(stdin_text: str, vault: Path) -> bool:
    """A Claude Code PostToolUse payload: act only when the edited file is inside the vault."""
    try:
        payload = json.loads(stdin_text or "{}")
    except ValueError:
        return False
    edited = (payload.get("tool_input") or {}).get("file_path")
    if not edited:
        return False
    try:
        Path(edited).resolve().relative_to(vault.resolve())
    except ValueError:
        return False
    return True


def cmd_guard(a: argparse.Namespace) -> int:
    if a.hook and not _hook_wants(sys.stdin.read(), a.vault):
        return 0
    if sum(bool(x) for x in (a.call, a.base, a.base_ref)) != 1:
        print("give one of --call SOURCE->TARGET, --base VAULT or --base-ref GIT_REF", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory() as tmp, open_store(a.vault, read_only=True) as conn:
        if a.call:
            source, _, target = a.call.partition("->")
            try:
                result = guard.simulate_call(conn, source.strip(), target.strip(), a.functions or None, a.mode, a.view)
            except ValueError as exc:
                print(exc, file=sys.stderr)
                return 2
        else:
            base_path = a.base or extract_plan(a.base_ref, Path(tmp), a.vault)
            with open_store(base_path, read_only=True) as base:
                result = guard.compare(base, conn, a.view)
    text = json.dumps(result.to_dict(), indent=2) if a.json else report.render_guard(result)
    if a.hook:
        # Claude Code shows a PostToolUse hook's stderr to the agent when the hook exits with 2.
        if result.blocking:
            print(text, file=sys.stderr)
            return 2
        return 0
    print(text)
    return 1 if result.blocking else 0


def cmd_export(a: argparse.Namespace) -> int:
    """The browser page's data: the graph as one Cypher script, the check queries, and the outage test results."""
    with open_store(a.vault, read_only=True) as conn:
        script = export_cypher(conn)
    a.out_dir.mkdir(parents=True, exist_ok=True)
    (a.out_dir / "graph.cypher").write_text(script, encoding="utf-8")
    (a.out_dir / "queries.json").write_text(json.dumps(checks.query_texts(), indent=2) + "\n", encoding="utf-8")
    for source, name in (("e1e2-results.json", "tests.json"), ("predictions.json", "predictions.json")):
        path = ROOT / "evidence" / source
        if path.exists():
            (a.out_dir / name).write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"graph ({len(script)} characters), queries and test results -> {a.out_dir}")
    return 0


def cmd_mcp(a: argparse.Namespace) -> int:
    from slowest_link.mcp_server import run

    run(a.vault)
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="slowest-link", description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    sub = ap.add_subparsers(dest="command", required=True)

    s = sub.add_parser("seed", help="build the plan vault from sources/")
    s.add_argument("--sources", type=Path, default=ROOT / "sources")
    s.add_argument("--vault", type=Path, default=DEFAULT_VAULT)
    s.set_defaults(run=cmd_seed)

    s = sub.add_parser("import-traces", help="add the calls seen in exported traces to the plan")
    s.add_argument("--traces", type=Path, default=ROOT / "evidence" / "e0-traces")
    s.add_argument("--vault", type=Path, default=DEFAULT_VAULT)
    s.add_argument("--date", required=True, help="the day the traces were recorded, YYYY-MM-DD")
    s.add_argument("--summary", type=Path, help="write the derived calls and counts to this JSON file")
    s.set_defaults(run=cmd_import_traces)

    s = sub.add_parser("check", help="run every check and print the findings")
    s.add_argument("--vault", type=Path, default=DEFAULT_VAULT)
    s.add_argument("--as-of", default=dt.date.today().isoformat(), help="assessment date, YYYY-MM-DD")
    s.add_argument("--json", action="store_true")
    s.add_argument("--fail-on-inversion", action="store_true", help="exit 1 when the view below finds an inversion")
    s.add_argument("--fail-view", choices=checks.VIEWS, default="evidence")
    s.set_defaults(run=cmd_check)

    s = sub.add_parser("explain", help="one function's dependencies in each view")
    s.add_argument("function")
    s.add_argument("--vault", type=Path, default=DEFAULT_VAULT)
    s.set_defaults(run=cmd_explain)

    s = sub.add_parser("whatif", help="read an outage notice and list the promises it breaks")
    s.add_argument("notice", help="the notice text, or - to read it from stdin")
    s.add_argument("--vault", type=Path, default=DEFAULT_VAULT)
    s.add_argument("--view", choices=checks.VIEWS, default="evidence")
    s.add_argument("--json", action="store_true")
    s.set_defaults(run=cmd_whatif)

    s = sub.add_parser("predict", help="for each fault, the functions each view expects it to reach")
    s.add_argument("--vault", type=Path, default=DEFAULT_VAULT)
    s.add_argument("--flags", type=Path, default=ROOT / "experiments" / "flags.csv")
    s.add_argument("--out", type=Path, default=ROOT / "evidence" / "predictions.json")
    s.add_argument("--commit", default="", help="the git commit of the vault the predictions come from")
    s.set_defaults(run=cmd_predict)

    s = sub.add_parser("score", help="compare measured effects with the frozen predictions")
    s.add_argument("--vault", type=Path, default=DEFAULT_VAULT)
    s.add_argument("--run", dest="run_dir", type=Path, default=ROOT / "evidence" / "e1e2")
    s.add_argument("--predictions", type=Path, default=ROOT / "evidence" / "predictions.json")
    s.add_argument("--out", type=Path, default=ROOT / "evidence" / "e1e2-results.json")
    s.set_defaults(run=cmd_score)

    s = sub.add_parser("record-tests", help="write the outage tests into the plan")
    s.add_argument("--vault", type=Path, default=DEFAULT_VAULT)
    s.add_argument("--run", dest="run_dir", type=Path, default=ROOT / "evidence" / "e1e2")
    s.add_argument("--date", required=True, help="the day the tests ran, YYYY-MM-DD")
    s.set_defaults(run=cmd_record_tests)

    s = sub.add_parser("guard", help="say which promises a new call, or a change to the plan, would break")
    s.add_argument("--vault", type=Path, default=DEFAULT_VAULT)
    s.add_argument("--call", help="a new call, SOURCE->TARGET")
    s.add_argument("--for", dest="functions", action="append", help="a function the new call serves (repeatable)")
    s.add_argument("--mode", choices=["sync", "async"], default="sync")
    s.add_argument("--base", type=Path, help="the plan before the change (a vault folder)")
    s.add_argument("--base-ref", help="the plan before the change, as it is at this git ref (for CI)")
    s.add_argument(
        "--hook", action="store_true", help="run as a Claude Code PostToolUse hook (reads its JSON on stdin)"
    )
    s.add_argument("--view", choices=checks.VIEWS, default="evidence")
    s.add_argument("--json", action="store_true")
    s.set_defaults(run=cmd_guard)

    s = sub.add_parser("export", help="write the plan graph as one Cypher script")
    s.add_argument("--vault", type=Path, default=DEFAULT_VAULT)
    s.add_argument("--out-dir", type=Path, default=ROOT / "web" / "data")
    s.set_defaults(run=cmd_export)

    s = sub.add_parser("mcp", help="serve the checks to agents over MCP (stdio)")
    s.add_argument("--vault", type=Path, default=DEFAULT_VAULT)
    s.set_defaults(run=cmd_mcp)
    return ap


def main(argv: list[str] | None = None) -> int:
    a = build_parser().parse_args(argv)
    code: int = a.run(a)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
