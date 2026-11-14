// The checks in the browser: the same Cypher as slowest_link/checks.py, the same what-if and guard rules as
// slowest_link/whatif.py and slowest_link/guard.py. tests/test_web_parity.py runs both and compares.

export const VIEWS = ["plan", "architecture", "evidence"];
const COMPONENT = "Service|Datastore|Queue";
const RELATIVE_SCORE = 0.6;
const STOP_WORDS = new Set(
  `a about after all also an and any are as at be been being but by can could down due during eta expect expected
  estimate estimated estimates for from has have hour hours in is it its min mins minute minutes more no not now of
  on or our out outage outages problem problems restore restored restoring service services some status than that
  the their them there these they this to until up we were what when which while will with within working yet
  affected affecting degraded degradation disruption error errors fail failed failing failure failures impact
  impacted incident incidents investigating issue issues unavailable unreachable broken slow`.split(/\s+/),
);

export function functions(graph, db) {
  return graph.rows(
    "MATCH (f:Function) RETURN f.name AS name, f.promise_min AS promise, f.critical AS critical, " +
      "f.description AS description ORDER BY name",
    null,
    db,
  );
}

export function profile(graph, view, name, db) {
  const found = graph.rows(graph.queries.profile[view], { function: name }, db);
  return found[0] || null;
}

export function reach(graph, view, db) {
  const result = {};
  for (const f of functions(graph, db)) result[f.name] = new Set();
  for (const row of graph.rows(graph.queries.reach[view], null, db)) result[row.function] = new Set(row.components);
  return result;
}

export function findings(graph, view, db) {
  const keyed = {};
  for (const check of ["inversions", "restore_chains"]) {
    for (const row of graph.rows(graph.queries[check][view], null, db)) {
      keyed[`${check}|${row.function}`] = { check, ...row };
    }
  }
  return keyed;
}

export function parseDuration(text) {
  const re =
    /(?:(\d+(?:\.\d+)?)\s*(?:h|hr|hrs|hour|hours)\b)?\s*(?:and\s*)?(?:(\d+)\s*(?:m|min|mins|minute|minutes)\b)?/gi;
  for (const m of text.matchAll(re)) {
    if (m[1] || m[2]) return Math.round(parseFloat(m[1] || "0") * 60 + parseInt(m[2] || "0", 10));
  }
  return null;
}

function escapeRe(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export function matchComponents(graph, notice, db) {
  const names = graph.rows(`MATCH (c:${COMPONENT}) RETURN c.name AS n`, null, db).map((r) => r.n);
  const lowered = notice.toLowerCase();
  const exact = names
    .filter((n) => new RegExp(`(?<![a-z0-9-])${escapeRe(n)}(?![a-z0-9-])`).test(lowered))
    .sort();
  const found = exact.map((n) => ({ component: n, how: "named", score: null }));
  const terms = (lowered.match(/[a-z][a-z0-9-]*/g) || []).filter((w) => !STOP_WORDS.has(w)).join(" ");
  if (terms) {
    const hits = graph.rows(
      "MATCH (n) SEARCH n IN (FULLTEXT INDEX component_text FOR $q LIMIT 5) SCORE AS score " +
        "RETURN n.name AS component, score ORDER BY score DESC",
      { q: terms },
      db,
    );
    if (hits.length) {
      const top = hits[0].score;
      for (const hit of hits) {
        if (hit.score >= RELATIVE_SCORE * top && !exact.includes(hit.component)) {
          found.push({ component: hit.component, how: "search", score: Math.round(hit.score * 1000) / 1000 });
        }
      }
    }
  }
  return found;
}

function dependencyFirst(graph, components, db) {
  const edges = graph.rows(
    `MATCH (a:${COMPONENT})-[r:CALLS]->(b:${COMPONENT}) WHERE a.name IN $names AND b.name IN $names ` +
      "AND (r.declared OR r.observed) RETURN a.name AS a, b.name AS b",
    { names: components },
    db,
  );
  const remaining = [...components].sort();
  const ordered = [];
  while (remaining.length) {
    const ready = remaining.filter((c) => !edges.some((e) => e.a === c && e.b !== c && remaining.includes(e.b)));
    const pick = ready.length ? ready[0] : remaining[0];
    ordered.push(pick);
    remaining.splice(remaining.indexOf(pick), 1);
  }
  return ordered;
}

export function whatIf(graph, notice, view = "evidence", db) {
  const matched = matchComponents(graph, notice, db);
  const outage = parseDuration(notice);
  const result = { view, components: matched, outage_min: outage, affected: [], restore_order: [] };
  if (!matched.length) return result;
  const names = matched.map((m) => m.component);
  const objectives = {};
  for (const row of graph.rows(
    `MATCH (c:${COMPONENT}) WHERE c.name IN $names RETURN c.name AS n, c.recovery_min AS r`,
    { names },
    db,
  )) {
    objectives[row.n] = row.r;
  }
  const deps = reach(graph, view, db);
  const fns = Object.fromEntries(functions(graph, db).map((f) => [f.name, f]));
  for (const name of Object.keys(deps).sort()) {
    const hit = names.filter((n) => deps[name].has(n)).sort();
    if (!hit.length) continue;
    const expected = outage ?? Math.max(...hit.map((c) => objectives[c]));
    const promise = fns[name].promise;
    result.affected.push({
      function: name,
      promise_min: promise,
      critical: Boolean(fns[name].critical),
      through: hit,
      expected_outage_min: expected,
      broken: expected > promise,
    });
  }
  result.affected.sort(
    (a, b) =>
      Number(!a.broken) - Number(!b.broken) ||
      a.promise_min - b.promise_min ||
      Number(!a.critical) - Number(!b.critical) ||
      (a.function < b.function ? -1 : a.function > b.function ? 1 : 0),
  );
  result.restore_order = [...dependencyFirst(graph, names, db), ...result.affected.map((r) => r.function)];
  return result;
}

// The guard: add source -> target for some functions on a copy, extend them down the target's synchronous calls,
// and report the findings that are new or worse in the view.
export function simulateCall(graph, source, target, served, view = "evidence") {
  const before = findings(graph, view);
  const db = graph.copy();
  try {
    const params = { s: source, t: target, fns: served };
    const existing = graph.rows(
      `MATCH (:${COMPONENT} {name: $s})-[r:CALLS]->(:${COMPONENT} {name: $t}) RETURN count(r) AS n`,
      params,
      db,
    )[0].n;
    if (existing) {
      graph.rows(
        `MATCH (:${COMPONENT} {name: $s})-[r:CALLS]->(:${COMPONENT} {name: $t}) ` +
          "SET r.declared = true, r.observed = true, r.mode = 'sync', " +
          "r.journeys = coalesce(r.journeys, []) + [f IN $fns WHERE NOT f IN coalesce(r.journeys, [])]",
        params,
        db,
      );
    } else {
      graph.rows(
        `MATCH (a:${COMPONENT} {name: $s}), (b:${COMPONENT} {name: $t}) ` +
          "CREATE (a)-[:CALLS {declared: true, observed: true, mode: 'sync', journeys: $fns, source: 'guard'}]->(b)",
        params,
        db,
      );
    }
    graph.rows(
      `MATCH (b:${COMPONENT} {name: $t}) MATCH p = ACYCLIC (b)-[rs:CALLS]->*(x) ` +
        "WHERE all(r IN rs WHERE r.observed = true AND r.mode = 'sync') UNWIND rs AS r WITH DISTINCT r " +
        "SET r.journeys = coalesce(r.journeys, []) + [f IN $fns WHERE NOT f IN coalesce(r.journeys, [])]",
      params,
      db,
    );
    const after = findings(graph, view, db);
    const result = { new: [], worse: [] };
    for (const [key, f] of Object.entries(after).sort()) {
      if (!(key in before)) result.new.push(f);
      else if (f.value > before[key].value) result.worse.push({ ...f, was: before[key].value });
    }
    return result;
  } finally {
    db.free();
  }
}
