"""E1 and E2: outage tests on the running shop, as `PROTOCOL.md` fixes them.

    python experiments/run_tests.py --demo-dir <opentelemetry-demo checkout> --out <folder>

Writes, in the output folder:
- probe.jsonl       every journey attempt (prober.py)
- timeline.jsonl    one line per test: phases, recovery per journey, remediation, flag confirmation
- backoffice.jsonl  per test, which placed orders reached the accounting ledger and the fraud detection log
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from prober import JOURNEYS, Prober  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
BASELINE_S, FAULT_S, STOP_RECOVERY_S, FLAG_OFF_S = 40, 60, 180, 60
BACKOFFICE_DELAY_S = 90
# Docker's disk lives on C: on the machine these tests ran on; stop cleanly before it fills.
MIN_FREE_GB = 10.0
DOCKER_DISK = "C:\\" if sys.platform == "win32" else "/"
HEALTHY_RUN, RECOVERED_RUN = 10, 5
# Restart order for remediation: stores first, then flags, then services, then the front.
RESTART_ORDER = [
    "astronomy-db", "valkey-cart", "kafka", "flagd", "product-catalog", "currency", "quote", "shipping", "payment",
    "email", "cart", "ad", "recommendation", "checkout", "accounting", "fraud-detection", "image-provider",
    "flagd-ui", "frontend", "frontend-proxy",
]  # fmt: skip


def log(message: str) -> None:
    print(time.strftime("%H:%M:%S"), message, file=sys.stderr, flush=True)


def docker(*args: str, check: bool = True) -> str:
    done = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=180)
    if check and done.returncode != 0:
        raise RuntimeError(f"docker {' '.join(args)}: {done.stderr.strip()}")
    return done.stdout


class Runner:
    def __init__(self, prober: Prober, demo_dir: Path, out: Path) -> None:
        self.prober = prober
        self.demo_dir = demo_dir
        self.out = out
        self.flag_file = demo_dir / "src" / "flagd" / "demo.flagd.json"
        self.flag_original = self.flag_file.read_text(encoding="utf-8")
        self.checks: list[threading.Thread] = []

    # --- observation -------------------------------------------------------------------------------------------
    def attempts(self, journey: str, since: float) -> list[dict[str, Any]]:
        with self.prober.lock:
            return [r for r in self.prober.records if r["journey"] == journey and r["t"] >= since]

    def healthy(self, since: float) -> bool:
        for journey in JOURNEYS:
            recent = self.attempts(journey, since)[-HEALTHY_RUN:]
            if len(recent) < HEALTHY_RUN or not all(r["ok"] for r in recent):
                return False
        return True

    def wait_healthy(self, limit_s: float) -> bool:
        start = time.time()
        while time.time() - start < limit_s:
            if self.healthy(start):
                return True
            time.sleep(2)
        return False

    def recovery(self, restored: float) -> dict[str, float | None]:
        """Seconds from the restore command to the start of each journey's first run of 5 successes."""
        result: dict[str, float | None] = {}
        for journey in JOURNEYS:
            run: list[dict[str, Any]] = []
            result[journey] = None
            for attempt in self.attempts(journey, restored):
                run = run + [attempt] if attempt["ok"] else []
                if len(run) == RECOVERED_RUN:
                    result[journey] = round(run[0]["t"] - restored, 1)
                    break
        return result

    # --- remediation -------------------------------------------------------------------------------------------
    def remediate(self) -> None:
        log("remediating: restarting the app services")
        for name in RESTART_ORDER:
            docker("restart", "-t", "5", name, check=False)
            time.sleep(2)
        if not self.wait_healthy(300):
            raise RuntimeError("the shop did not come back healthy after a full restart")

    # --- back office -------------------------------------------------------------------------------------------
    def schedule_backoffice(self, test: dict[str, Any]) -> None:
        def run() -> None:
            time.sleep(max(0.0, test["t_end"] + BACKOFFICE_DELAY_S - time.time()))
            orders = [
                {"id": r["order_id"], "t": r["t"]}
                for r in self.attempts("user_checkout_single", test["t_baseline"])
                if r.get("order_id") and r["t"] < test["t_fault_end"]
            ]
            ids = [o["id"] for o in orders]
            ledger: set[str] | None = None
            for _ in range(60):
                try:
                    ledger = self.ledger_ids(ids)
                    break
                except RuntimeError:
                    time.sleep(10)
            fraud = self.fraud_ids(test["t_baseline"])
            row = {
                "test": test["test"],
                "checked_at": round(time.time(), 1),
                "orders": orders,
                "in_ledger": sorted(ledger) if ledger is not None else None,
                "in_fraud_log": sorted(set(ids) & fraud),
            }
            with (self.out / "backoffice.jsonl").open("a", encoding="utf-8") as sink:
                sink.write(json.dumps(row) + "\n")

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        self.checks.append(thread)

    @staticmethod
    def ledger_ids(ids: list[str]) -> set[str]:
        if not ids:
            return set()
        values = ",".join(f"'{i}'" for i in ids if all(c in "0123456789abcdef-" for c in i))
        sql = f'SELECT order_id FROM accounting."order" WHERE order_id IN ({values})'
        out = docker("exec", "astronomy-db", "psql", "-U", "postgres", "-d", "astronomy_db", "-t", "-A", "-c", sql)
        return {line.strip() for line in out.splitlines() if line.strip()}

    @staticmethod
    def fraud_ids(since: float) -> set[str]:
        # Order ids are unique, so the retained log is matched by id: Docker's VM clock can differ from the host's,
        # which makes a time filter (`--since`) unreliable.
        out = docker("logs", "--tail", "40000", "fraud-detection", check=False)
        found = set()
        for line in out.splitlines():
            if "orderId:" in line:
                found.add(line.split("orderId:", 1)[1].split(",", 1)[0].strip())
        return found

    # --- flags -------------------------------------------------------------------------------------------------
    def set_flag(self, flag: str, variant: str) -> bool:
        data = json.loads(self.flag_original)
        data["flags"][flag]["defaultVariant"] = variant
        self.flag_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return self.confirm_flag(flag, variant)

    def reset_flags(self, flag: str) -> bool:
        self.flag_file.write_text(self.flag_original, encoding="utf-8")
        return self.confirm_flag(flag, json.loads(self.flag_original)["flags"][flag]["defaultVariant"])

    def confirm_flag(self, flag: str, variant: str) -> bool:
        for _ in range(15):
            try:
                # flagd gets a new host port each time it restarts, so look it up on every check.
                port = docker("port", "flagd", "8016").splitlines()[0].rsplit(":", 1)[1]
                url = f"http://localhost:{port}/ofrep/v1/evaluate/flags/{flag}"
                req = urllib.request.Request(url, data=b'{"context":{}}', method="POST")
                req.add_header("Content-Type", "application/json")
                with urllib.request.urlopen(req, timeout=5) as response:
                    if json.load(response).get("variant") == variant:
                        return True
            except (OSError, RuntimeError, IndexError):
                pass
            time.sleep(1)
        return False

    # --- tests -------------------------------------------------------------------------------------------------
    def run_test(self, test: dict[str, Any]) -> dict[str, Any]:
        free_gb = shutil.disk_usage(DOCKER_DISK).free / 1e9
        if free_gb < MIN_FREE_GB:
            raise RuntimeError(f"only {free_gb:.1f} GB free on {DOCKER_DISK}; stopping before Docker's disk fills")
        if not self.wait_healthy(240):
            self.remediate()
        log(f"{test['test']}: baseline")
        test["t_baseline"] = round(time.time(), 2)
        time.sleep(BASELINE_S)
        test["t_fault"] = round(time.time(), 2)
        if test["kind"] == "stop":
            docker("stop", "-t", "5", test["target"])
            log(f"{test['test']}: stopped")
            time.sleep(max(0.0, test["t_fault"] + FAULT_S - time.time()))
            test["t_fault_end"] = round(time.time(), 2)
            docker("start", test["target"])
            log(f"{test['test']}: started")
            limit = STOP_RECOVERY_S
        else:
            test["flag_on_confirmed"] = self.set_flag(test["flag"], test["variant"])
            log(f"{test['test']}: flag on (confirmed {test['flag_on_confirmed']})")
            time.sleep(max(0.0, test["t_fault"] + FAULT_S - time.time()))
            test["t_fault_end"] = round(time.time(), 2)
            test["flag_off_confirmed"] = self.reset_flags(test["flag"])
            limit = FLAG_OFF_S
        deadline = test["t_fault_end"] + limit
        while time.time() < deadline:
            if all(v is not None for v in self.recovery(test["t_fault_end"]).values()):
                break
            time.sleep(2)
        if test["kind"] == "flag":
            time.sleep(max(0.0, deadline - time.time()))
        test["recovery_s"] = self.recovery(test["t_fault_end"])
        test["not_recovered"] = sorted(j for j, v in test["recovery_s"].items() if v is None)
        test["t_end"] = round(time.time(), 2)
        test["remediated"] = False
        if test["kind"] == "stop" and test["not_recovered"]:
            log(f"{test['test']}: not recovered on its own: {test['not_recovered']}")
            self.remediate()
            test["remediated"] = True
        with (self.out / "timeline.jsonl").open("a", encoding="utf-8") as sink:
            sink.write(json.dumps(test) + "\n")
        self.schedule_backoffice(test)
        return test


def plan_tests(only: list[str] | None) -> list[dict[str, Any]]:
    with (ROOT / "evidence" / "predictions.json").open(encoding="utf-8") as handle:
        faults = json.load(handle)["faults"]
    with (ROOT / "experiments" / "flags.csv").open(encoding="utf-8", newline="") as handle:
        flags = {row["flag"]: row for row in csv.DictReader(handle)}
    stops = [f for f in faults if f["kind"] == "stop"]
    # The database goes last among the stops: the back-office check reads the ledger from it.
    stops.sort(key=lambda f: (f["target"] == "astronomy-db", f["target"]))
    tests = [{"test": f["id"], "kind": "stop", "target": f["target"]} for f in stops]
    for f in faults:
        if f["kind"] == "flag":
            name = f["id"].split(":", 1)[1]
            tests.append({"test": f["id"], "kind": "flag", "target": f["target"], "flag": name,
                          "variant": flags[name]["variant"]})  # fmt: skip
    if only:
        tests = [t for t in tests if t["test"] in only]
    return tests


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo-dir", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--base", default="http://localhost:8080")
    ap.add_argument("--only", nargs="*", help="run only these test ids")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)

    try:
        urllib.request.urlopen(urllib.request.Request(f"{a.base}/loadgen/stop"), timeout=10).read()
        log("load generator stopped")
    except OSError as exc:
        log(f"could not stop the load generator: {exc}")

    prober = Prober(a.base, a.out / "probe.jsonl")
    prober.start()
    runner = Runner(prober, a.demo_dir, a.out)
    tests = plan_tests(a.only)
    log(f"{len(tests)} tests")
    try:
        for test in tests:
            runner.run_test(test)
    finally:
        runner.flag_file.write_text(runner.flag_original, encoding="utf-8")
        for thread in runner.checks:
            thread.join(timeout=900)
        prober.stop.set()
        time.sleep(11)
        log("done")


if __name__ == "__main__":
    main()
