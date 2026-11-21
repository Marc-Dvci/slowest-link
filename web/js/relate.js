// Relate by Neo4j, compiled to WebAssembly, running the plan graph in this tab.
// The graph is the plan vault exported to one Cypher script (python -m slowest_link export); the queries are the
// exact Cypher the command line and the MCP server run (slowest_link/checks.py).

export const RELATE_VERSION = "1.2.0";
const RELATE_URL = `https://cdn.jsdelivr.net/npm/@relate/relate-wasm@${RELATE_VERSION}/relate.js`;

export class Graph {
  constructor(db, script) {
    this.db = db;
    this.script = script;
  }

  static async load(dataUrl = "data/") {
    const started = performance.now();
    const [{ default: init, RelateDb }, script, queries] = await Promise.all([
      import(RELATE_URL),
      fetch(dataUrl + "graph.cypher").then((r) => r.text()),
      fetch(dataUrl + "queries.json").then((r) => r.json()),
    ]);
    await init();
    const graph = new Graph(new RelateDb(), script);
    graph.RelateDb = RelateDb;
    graph.queries = queries;
    graph.runScript(graph.db, script);
    graph.loadMs = Math.round(performance.now() - started);
    return graph;
  }

  runScript(db, script) {
    for (const envelope of db.executeScript(script, null).map((e) => JSON.parse(e))) {
      if (envelope.error) throw new Error(envelope.error);
    }
  }

  // One statement on a database (this graph by default): its rows, or an Error.
  rows(query, params = null, db = this.db) {
    const result = JSON.parse(db.execute(query, params ? JSON.stringify(params) : null));
    if (result.error) throw new Error(result.error);
    return result.rows;
  }

  // A fresh in-memory copy of the plan, safe to change (the guard tries changes on it).
  copy() {
    const db = new this.RelateDb();
    this.runScript(db, this.script);
    return db;
  }
}
