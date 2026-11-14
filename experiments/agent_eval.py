"""Agent evaluation: the same continuity questions, answered by one model in two ways.

    python experiments/agent_eval.py freeze            # write the questions and their answers from the checks
    python experiments/agent_eval.py run --repeats 3   # ask the model (needs DASHSCOPE_API_KEY or ~/.bailian)
    python experiments/agent_eval.py grade             # grade the recorded answers (no key needed)

- **files**: the model reads every note of the plan vault, pasted into its context.
- **tools**: the model calls the Slowest Link tools (the MCP server's tools, run in process on Relate).

The answers come from the deterministic checks and are frozen before any model runs. Each recorded answer is graded
by exact match: the same set of names, or the same number.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from slowest_link import checks, guard, whatif  # noqa: E402
from slowest_link.mcp_server import build_server  # noqa: E402
from slowest_link.store import open_store, rows  # noqa: E402

OUT = ROOT / "evidence" / "agent-eval"
VAULT = ROOT / "plan"
MODEL = "qwen3.8-flash"
MAX_TOOL_ROUNDS = 8
SYSTEM = (
    "You answer questions about a business continuity plan for an online shop. Each function has a recovery promise "
    "in minutes; each component has a recovery time in minutes. Unless a question says otherwise, use what each "
    "function really calls as seen in its traces (calls marked observed for that function, synchronous ones only, "
    "plus asynchronous calls a test proved the function needs (needed_by), and leaving out calls a test proved the "
    "function survives without (survives_without)). "
    'Reply with JSON only, as {"answer": ...}: a list of names when the question asks which, a number when it asks '
    "how long or how many."
)


def questions() -> list[dict[str, Any]]:
    """The questions, with answers computed by the checks on the committed plan."""
    with open_store(VAULT, read_only=True) as conn:
        inv = {f.function: f for f in checks.inversions(conn, "evidence")}
        chains = {f.function: f for f in checks.restore_chains(conn, "evidence")}
        gaps = {g["function"]: [m["component"] for m in g["missing"]] for g in checks.plan_gaps(conn, "evidence")}
        shared = checks.shared_points(conn, "evidence")
        top = max(len(s["functions"]) for s in shared)
        unseen = checks.unseen_calls(conn)
        reach = checks.reach(conn, "evidence")
        db_down = whatif.what_if(conn, "astronomy-db is down for 3 hours")
        kafka_down = whatif.what_if(conn, "kafka is down for 3 hours")
        home = guard.simulate_call(conn, "frontend", "product-catalog", ["Browse the shop"])
        place = checks.profile(conn, "evidence", "Place an order")
        view = checks.profile(conn, "evidence", "View a product")
        record = rows(conn, "MATCH (f:Function {name: 'Record orders in accounting'}) RETURN f.promise_min AS p")[0][
            "p"
        ]
    chain_only = sorted(f for f in chains if f not in inv)
    return [
        {"id": "q01", "kind": "names", "question": "Which functions cannot keep their recovery promise because one of "
         "their dependencies takes longer to recover than the promise?", "answer": sorted(inv)},
        {"id": "q02", "kind": "number", "question": "How many minutes is the longest restore chain under 'Place an "
         "order' (the recovery times added up along one dependency path, from its entry point)?",
         "answer": place["longest"]["chain"]},
        {"id": "q03", "kind": "names", "question": "Which components does 'Place an order' depend on that the plan's "
         "own list of components for it (its USES links) leaves out?", "answer": sorted(gaps.get("Place an order", []))},
        {"id": "q04", "kind": "names", "question": "Which functions have a restore chain longer than their promise "
         "even though no single dependency takes longer to recover than the promise?", "answer": chain_only},
        {"id": "q05", "kind": "names", "question": "The database astronomy-db is down for 3 hours. Which functions "
         "break their promise?", "answer": sorted(r["function"] for r in db_down.broken)},
        {"id": "q06", "kind": "names", "question": "The kafka queue is down for 3 hours. Which functions break their "
         "promise? Answer an empty list if none do.", "answer": sorted(r["function"] for r in kafka_down.broken)},
        {"id": "q07", "kind": "names", "question": "Which components sit under the largest number of critical "
         "functions?", "answer": sorted(s["component"] for s in shared if len(s["functions"]) == top)},
        {"id": "q08", "kind": "number", "question": "How many calls does the published architecture declare that no "
         "trace has shown?", "answer": len(unseen)},
        {"id": "q09", "kind": "names", "question": "A developer makes the frontend call product-catalog when it "
         "renders the home page ('Browse the shop'). Which functions would then break their promise?",
         "answer": sorted({f["function"] for f in home.new + home.worse})},
        {"id": "q10", "kind": "names", "question": "If the ad service is lost, which functions lose a dependency?",
         "answer": sorted(f for f, deps in reach.items() if "ad" in deps)},
        {"id": "q11", "kind": "number", "question": "How many minutes does the slowest component under 'View a "
         "product' take to recover?", "answer": view["slowest"]["recovery"]},
        {"id": "q12", "kind": "number", "question": "What is the recovery promise of 'Record orders in accounting', "
         "in minutes?", "answer": record},
    ]  # fmt: skip


# --- the two ways of answering ------------------------------------------------------------------------------------


def files_context() -> str:
    notes = sorted(p for p in VAULT.rglob("*.md") if p.name not in {"index.md", "log.md"})
    return "\n\n".join(f"=== {p.relative_to(VAULT).as_posix()} ===\n{p.read_text(encoding='utf-8')}" for p in notes)


def tool_specs_and_runner() -> tuple[list[dict[str, Any]], Any]:
    """The MCP server's tools as chat-completion function specs, and a runner that calls them in process."""
    server = build_server(VAULT)
    manager = server._tool_manager  # noqa: SLF001 - the tools exactly as the MCP server registers them
    specs, functions = [], {}
    for tool in manager.list_tools():
        specs.append(
            {
                "type": "function",
                "function": {"name": tool.name, "description": tool.description, "parameters": tool.parameters},
            }
        )
        functions[tool.name] = tool.fn

    def run(name: str, arguments: dict[str, Any]) -> str:
        if name not in functions:
            return json.dumps({"error": f"no tool {name}"})
        try:
            return json.dumps(functions[name](**arguments), default=str)
        except Exception as exc:  # the model sent bad arguments: tell it, as the MCP server would
            return json.dumps({"error": f"{type(exc).__name__}: {exc}"})

    return specs, run


def credentials() -> tuple[str, str]:
    key = os.environ.get("DASHSCOPE_API_KEY")
    base = os.environ.get("DASHSCOPE_BASE_URL", "https://dashscope-intl.aliyuncs.com")
    if not key:
        config = Path.home() / ".bailian" / "config.json"
        data = json.loads(config.read_text(encoding="utf-8"))
        key, base = data["api_key"], data.get("base_url", base)
    return key, base.rstrip("/") + "/compatible-mode/v1/chat/completions"


def chat(url: str, key: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None) -> dict[str, Any]:
    body: dict[str, Any] = {"model": MODEL, "messages": messages, "temperature": 0}
    if tools:
        body["tools"] = tools
    data = json.dumps(body).encode()
    for attempt in range(4):
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Authorization", f"Bearer {key}")
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=180) as response:
                result: dict[str, Any] = json.load(response)
            return result
        except (TimeoutError, OSError):
            if attempt == 3:
                raise
            time.sleep(10 * (attempt + 1))  # a slow or dropped call is retried; the request is the same
    raise RuntimeError("unreachable")


def ask(mode: str, question: str, url: str, key: str, specs: list[dict[str, Any]], run: Any) -> dict[str, Any]:
    messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM}]
    if mode == "files":
        messages.append({"role": "user", "content": f"The plan's notes:\n\n{files_context()}\n\nQuestion: {question}"})
    else:
        messages.append({"role": "user", "content": question})
    calls: list[dict[str, Any]] = []
    usage = {"prompt_tokens": 0, "completion_tokens": 0}
    for _ in range(MAX_TOOL_ROUNDS + 1):
        reply = chat(url, key, messages, specs if mode == "tools" else None)
        for k in usage:
            usage[k] += int(reply.get("usage", {}).get(k, 0))
        message = reply["choices"][0]["message"]
        tool_calls = message.get("tool_calls") or []
        if not tool_calls:
            return {"text": message.get("content") or "", "tool_calls": calls, "usage": usage}
        messages.append({"role": "assistant", "content": message.get("content") or "", "tool_calls": tool_calls})
        for call in tool_calls:
            name = call["function"]["name"]
            try:
                arguments = json.loads(call["function"].get("arguments") or "{}")
            except ValueError:
                arguments = {}
            output = run(name, arguments)
            calls.append({"name": name, "arguments": arguments})
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": output})
    return {"text": "", "tool_calls": calls, "usage": usage, "stopped": "too many tool rounds"}


# --- grading --------------------------------------------------------------------------------------------------------


def parse_answer(text: str) -> Any:
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return None
    try:
        return json.loads(match.group(0)).get("answer")
    except (ValueError, AttributeError):
        return None


def correct(kind: str, truth: Any, given: Any) -> bool:
    if kind == "number":
        try:
            return float(given) == float(truth)
        except (TypeError, ValueError):
            return False
    if not isinstance(given, list):
        return False
    return {str(x).strip().lower() for x in given} == {str(x).strip().lower() for x in truth}


def grade(qs: list[dict[str, Any]], runs: list[dict[str, Any]]) -> dict[str, Any]:
    truth = {q["id"]: q for q in qs}
    table: dict[str, dict[str, Any]] = {}
    for r in runs:
        q = truth[r["id"]]
        ok = correct(q["kind"], q["answer"], parse_answer(r["text"]))
        row = table.setdefault(r["mode"], {"answers": 0, "correct": 0, "tool_calls": 0, "prompt_tokens": 0})
        row["answers"] += 1
        row["correct"] += ok
        row["tool_calls"] += len(r["tool_calls"])
        row["prompt_tokens"] += r["usage"]["prompt_tokens"]
    for row in table.values():
        row["share"] = round(row["correct"] / row["answers"], 3) if row["answers"] else None
    return table


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["freeze", "run", "grade"])
    ap.add_argument("--repeats", type=int, default=3)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    qfile, rfile = OUT / "questions.json", OUT / "runs.jsonl"
    if a.step == "freeze":
        qfile.write_text(json.dumps(questions(), indent=2) + "\n", encoding="utf-8")
        print(f"{len(questions())} questions -> {qfile.relative_to(ROOT)}")
        return
    qs = json.loads(qfile.read_text(encoding="utf-8"))
    if a.step == "run":
        key, url = credentials()
        specs, run = tool_specs_and_runner()
        done = set()
        if rfile.exists():  # resume: answers already recorded are kept
            for line in rfile.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    r = json.loads(line)
                    done.add((r["id"], r["mode"], r["repeat"]))
        with rfile.open("a", encoding="utf-8") as sink:
            for repeat in range(a.repeats):
                for mode in ("files", "tools"):
                    for q in qs:
                        if (q["id"], mode, repeat) in done:
                            continue
                        started = time.time()
                        result = ask(mode, q["question"], url, key, specs, run)
                        record = {"id": q["id"], "mode": mode, "repeat": repeat, "model": MODEL,
                                  "seconds": round(time.time() - started, 1), **result}  # fmt: skip
                        sink.write(json.dumps(record) + "\n")
                        sink.flush()
                        print(q["id"], mode, repeat, correct(q["kind"], q["answer"], parse_answer(result["text"])))
    runs = [json.loads(line) for line in rfile.read_text(encoding="utf-8").splitlines() if line.strip()]
    summary = grade(qs, runs)
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
