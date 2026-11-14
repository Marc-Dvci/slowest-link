"""E0: export the running shop's traces from Jaeger, one file per journey and per consumer.

    python experiments/export_traces.py --jaeger http://localhost:8080/jaeger/ui --out evidence/e0-traces

Each trace keeps only the fields the derivation reads (span ids, parent references, operation names, times, the
span kind and peer attributes, and each process's service name), so the evidence stays small enough to commit.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
KEEP_TAGS = {
    "span.kind",
    "db.system",
    "db.system.name",
    "messaging.system",
    "messaging.destination.name",
    "server.address",
    "net.peer.name",
    "peer.service",
    "rpc.service",
    "rpc.method",
    "http.route",
    "http.response.status_code",
    "rpc.grpc.status_code",
    "error",
    "otel.status_code",
}


def slim(trace: dict[str, Any]) -> dict[str, Any]:
    return {
        "traceID": trace["traceID"],
        "processes": {pid: {"serviceName": p["serviceName"]} for pid, p in trace["processes"].items()},
        "spans": [
            {
                "spanID": s["spanID"],
                "operationName": s["operationName"],
                "references": [{"refType": r["refType"], "spanID": r["spanID"]} for r in s.get("references") or []],
                "startTime": s["startTime"],
                "duration": s["duration"],
                "processID": s["processID"],
                "tags": [t for t in s.get("tags") or [] if t["key"] in KEEP_TAGS],
            }
            for s in trace["spans"]
        ],
    }


def fetch(base: str, service: str, operation: str | None, limit: int, lookback: str) -> list[dict[str, Any]]:
    query = {"service": service, "limit": str(limit), "lookback": lookback}
    if operation:
        query["operation"] = operation
    url = f"{base}/api/traces?{urllib.parse.urlencode(query)}"
    with urllib.request.urlopen(url, timeout=120) as response:
        data: list[dict[str, Any]] = json.load(response)["data"]
    return data


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jaeger", default="http://localhost:8080/jaeger/ui")
    ap.add_argument("--out", type=Path, default=ROOT / "evidence" / "e0-traces")
    ap.add_argument("--limit", type=int, default=400)
    ap.add_argument("--lookback", default="2h")
    a = ap.parse_args()

    with (ROOT / "sources" / "business-impact-analysis.csv").open(encoding="utf-8", newline="") as handle:
        bia = list(csv.DictReader(handle))
    journeys = [j for row in bia for j in row["journeys"].split(";") if j]
    consumers = [row["enters"] for row in bia if row["enters"] != "frontend-proxy"]

    a.out.mkdir(parents=True, exist_ok=True)
    targets = [("load-generator", j) for j in journeys] + [(c, None) for c in consumers]
    for service, operation in targets:
        traces = [slim(t) for t in fetch(a.jaeger, service, operation, a.limit, a.lookback)]
        name = operation or service
        path = a.out / f"{name}.json.gz"
        with gzip.open(path, "wt", encoding="utf-8") as handle:
            json.dump({"service": service, "operation": operation, "data": traces}, handle)
        print(f"{name}: {len(traces)} traces -> {path.relative_to(ROOT)}", file=sys.stderr)


if __name__ == "__main__":
    main()
