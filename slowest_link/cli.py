"""Command line: `python -m slowest_link <command>`.

    seed           build the plan vault from sources/
    import-traces  add the calls seen in exported traces to the plan
    check          run every check and print the findings
    explain        show one function's dependencies, slowest link and restore chain in each view
    whatif         read an outage notice and list the promises it breaks, with a restore order
    predict        list, for each fault, the functions each view expects it to reach
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import json
import sys
from pathlib import Path
from typing import Any

from slowest_link import checks, report, whatif
from slowest_link.evidence import import_derivation, plan_maps
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
        components = sorted(
            row["n"] for row in conn.execute("MATCH (c:Service|Datastore|Queue) RETURN c.name AS n")
        )
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


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="slowest-link", description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
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
    return ap


def main(argv: list[str] | None = None) -> int:
    a = build_parser().parse_args(argv)
    code: int = a.run(a)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
