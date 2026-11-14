// The browser code gives the command line's answers: run web/js/checks.js on Relate's WebAssembly build (from npm)
// and compare with web/test/parity.json, which tests/test_web_parity.py proves matches the Python code.
//   cd web && npm ci && node test/parity.mjs
import fs from "node:fs";
import { createRequire } from "node:module";
import { initSync, RelateDb } from "@relate/relate-wasm";
import { Graph } from "../js/relate.js";
import { simulateCall, whatIf } from "../js/checks.js";

const here = new URL(".", import.meta.url);
const require = createRequire(import.meta.url);
initSync({ module: fs.readFileSync(require.resolve("@relate/relate-wasm/relate_bg.wasm")) });

const script = fs.readFileSync(new URL("../data/graph.cypher", here), "utf8");
const graph = new Graph(new RelateDb(), script);
graph.RelateDb = RelateDb;
graph.queries = JSON.parse(fs.readFileSync(new URL("../data/queries.json", here), "utf8"));
graph.runScript(graph.db, script);
const expected = JSON.parse(fs.readFileSync(new URL("parity.json", here), "utf8"));

let failures = 0;
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
for (const want of expected.whatif) {
  const got = whatIf(graph, want.notice, want.view);
  const fields = ["components", "outage_min", "affected", "restore_order"];
  for (const field of fields) {
    if (!same(got[field], want[field])) {
      failures += 1;
      console.error(`what-if [${want.view}] "${want.notice}": ${field}\n  js:     ${JSON.stringify(got[field])}\n  python: ${JSON.stringify(want[field])}`);
    }
  }
}
for (const want of expected.guard) {
  const r = simulateCall(graph, want.source, want.target, want.functions);
  const check = (c) => (c === "inversions" ? "inversion" : "restore_chain");
  const got = {
    new: r.new.map((f) => [check(f.check), f.function, f.value]).sort(),
    worse: r.worse.map((f) => [check(f.check), f.function, f.was, f.value]).sort(),
  };
  if (!same(got.new, want.new) || !same(got.worse, want.worse)) {
    failures += 1;
    console.error(`guard ${want.source} -> ${want.target}\n  js:     ${JSON.stringify(got)}\n  python: ${JSON.stringify({ new: want.new, worse: want.worse })}`);
  }
}
const total = expected.whatif.length + expected.guard.length;
console.log(`${total - failures} of ${total} cases give the same answer in the browser code and the Python code`);
process.exit(failures ? 1 : 0);
