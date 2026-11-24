import { Graph, RELATE_VERSION } from "./relate.js";
import { VIEWS, functions, profile, simulateCall, whatIf } from "./checks.js";

// Line colours, one per function, in the spirit of a metro map. Red is kept for broken promises.
const LINE = {
  "Browse the shop": "#0098d4",
  "View a product": "#00782a",
  "Add to cart": "#9b0056",
  "View cart": "#e05a9c",
  "Place an order": "#003688",
  "Show recommendations": "#4fa594",
  "Show ads": "#868f98",
  "Record orders in accounting": "#e0a800",
  "Screen orders for fraud": "#b36305",
};
const RED = "#dc241f";
const VIEW_LABEL = {
  plan: "Plan",
  architecture: "Architecture",
  evidence: "Evidence",
};
const VIEW_NOTE = {
  plan: "Each component the plan lists for a function, on its own: how plans are checked today.",
  architecture: "Every call the published architecture declares, followed through: it overstates what a function needs.",
  evidence: "The calls each function makes in its own traces, synchronous only, minus calls an outage test proved it survives without.",
};
const EXAMPLES = [
  "Our managed PostgreSQL database is down. Estimated restore: 3 hours.",
  "Kafka brokers unavailable, recovery expected in 2 hours.",
  "Card payments are failing at the payment service, ETA 45 minutes.",
];

const $ = (sel) => document.querySelector(sel);
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

export function minutes(value) {
  if (value === null || value === undefined) return "-";
  const h = Math.floor(value / 60);
  const m = Math.round(value % 60);
  if (!h) return `${m} min`;
  return m ? `${h} h ${String(m).padStart(2, "0")} min` : `${h} h`;
}

const state = { graph: null, view: "evidence", selected: "Place an order", fns: [], tests: null };

function read(param, fallback, allowed) {
  const value = new URLSearchParams(location.search).get(param);
  return value && (!allowed || allowed.includes(value)) ? value : fallback;
}

function writeUrl() {
  const params = new URLSearchParams(location.search);
  params.set("view", state.view);
  params.set("function", state.selected);
  history.replaceState(null, "", `${location.pathname}?${params}${location.hash}`);
}

// --- the line diagram ------------------------------------------------------------------------------------------------

function chainOf(p) {
  // Stations in restore order: the deepest dependency first, the function's entry point last.
  if (!p || !p.longest) return [];
  const names = [...p.longest.names].reverse();
  const rec = Object.fromEntries((p.recoveries || []).map((r) => [r.name, r.recovery]));
  let t = 0;
  return names.map((name) => {
    t += rec[name];
    return { name, recovery: rec[name], at: t };
  });
}

function recoveries(graph) {
  return graph.rows("MATCH (c:Service|Datastore|Queue) RETURN c.name AS name, c.recovery_min AS recovery");
}

function drawMap() {
  const { graph, view } = state;
  const rec = recoveries(graph);
  const rows = state.fns.map((f) => {
    const p = profile(graph, view, f.name);
    if (p) p.recoveries = rec;
    return { f, p, chain: chainOf(p) };
  });
  const width = 1120;
  const left = 250;
  const right = width - 175;
  const maxChain = Math.max(360, ...rows.map((r) => (r.chain.length ? r.chain[r.chain.length - 1].at : 0)));
  const scaleMax = Math.ceil((maxChain + 30) / 60) * 60;
  const x = (m) => left + ((right - left) * Math.min(m, scaleMax)) / scaleMax;
  const rowH = 128;
  const top = 58;
  const height = top + rows.length * rowH + 34;
  const parts = [];
  // The hour scale runs along the bottom, clear of the station names above each line.
  for (let m = 0; m <= scaleMax; m += 60) {
    parts.push(`<line x1="${x(m)}" y1="${top}" x2="${x(m)}" y2="${height - 26}" class="grid"/>`);
    parts.push(`<text x="${x(m)}" y="${height - 8}" class="tick" text-anchor="middle">${m ? `${m / 60} h` : "0"}</text>`);
  }
  rows.forEach((row, i) => {
    const y = top + i * rowH + 62;
    const colour = LINE[row.f.name] || "#333";
    const end = row.chain.length ? row.chain[row.chain.length - 1].at : 0;
    const promise = row.f.promise;
    const late = end > promise;
    const selected = row.f.name === state.selected;
    parts.push(`<g class="row${selected ? " selected" : ""}" data-fn="${esc(row.f.name)}" tabindex="0" role="button"
      aria-label="${esc(row.f.name)}: promises ${minutes(promise)}, restore chain ${minutes(end)}${late ? ", broken" : ", kept"}">`);
    parts.push(`<rect x="0" y="${y - 70}" width="${width}" height="${rowH}" class="hit"/>`);
    parts.push(`<rect x="12" y="${y - 3}" width="22" height="6" rx="3" fill="${colour}"/>`);
    parts.push(`<text x="44" y="${y - 6}" class="fname">${esc(row.f.name)}</text>`);
    parts.push(`<text x="44" y="${y + 13}" class="fmeta">promises ${minutes(promise)}${row.f.critical ? " · critical" : ""}</text>`);
    if (late) {
      parts.push(`<line x1="${x(promise)}" y1="${y}" x2="${x(end)}" y2="${y}" stroke="${RED}" stroke-width="14" stroke-linecap="round"/>`);
    }
    if (end > 0) {
      parts.push(`<line x1="${x(0)}" y1="${y}" x2="${x(end)}" y2="${y}" stroke="${colour}" stroke-width="8" stroke-linecap="round"/>`);
    }
    const slowest = row.chain.reduce((a, b) => (b.recovery > (a ? a.recovery : -1) ? b : a), null);
    row.chain.forEach((s) => {
      const ring = s === slowest ? `<circle cx="${x(s.at)}" cy="${y}" r="11" fill="none" stroke="${RED}" stroke-width="3"/>` : "";
      parts.push(`${ring}<circle cx="${x(s.at)}" cy="${y}" r="6.5" class="station"/>`);
      parts.push(`<text transform="translate(${x(s.at) + 3},${y - 14}) rotate(-55)" class="sname${s === slowest && s.recovery > promise ? " slow" : ""}">${esc(s.name)} · ${minutes(s.recovery)}</text>`);
    });
    const tick = promise <= scaleMax ? x(promise) : right;
    parts.push(`<line x1="${tick}" y1="${y - 16}" x2="${tick}" y2="${y + 16}" class="promise"/>`);
    const first = end === 0 ? "nothing under it" : minutes(end);
    const beyond = promise > scaleMax ? `, promise ${minutes(promise)}` : "";
    const second = end === 0 ? "" : late ? `${minutes(end - promise)} late` : `kept${beyond}`;
    parts.push(`<text x="${right + 26}" y="${y - 1}" class="verdict${late ? " late" : ""}">${first}</text>`);
    parts.push(`<text x="${right + 26}" y="${y + 16}" class="vnote${late ? " late" : ""}">${second}</text>`);
    parts.push("</g>");
  });
  const svg = $("#map");
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.innerHTML = parts.join("");
  svg.querySelectorAll(".row").forEach((g) => {
    const pick = () => select(g.dataset.fn);
    g.addEventListener("click", pick);
    g.addEventListener("keydown", (e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), pick()));
  });
  const broken = rows.filter((r) => r.chain.length && r.chain[r.chain.length - 1].at > r.f.promise).length;
  $("#map-summary").textContent = `${VIEW_LABEL[view]} view: ${broken} of ${rows.length} functions cannot be restored within their promise.`;
}

// --- the selected function ------------------------------------------------------------------------------------------

function stationList(names, slow) {
  return `<ol class="stops">${names
    .map((n) => `<li class="${n === slow ? "slow" : ""}"><span class="dot"></span>${esc(n)}</li>`)
    .join("")}</ol>`;
}

function testsFor(fn, deps) {
  if (!state.tests) return "";
  const rows = state.tests.outcomes
    .filter((o) => o.kind === "stop")
    .map((o) => {
      const hit = o.affected.includes(fn);
      const listed = deps.has(o.target);
      if (!hit && !listed) return null;
      const journey = Object.entries(o.journeys).find(([, j]) => j.function === fn);
      const rec = journey ? o.recovery_s[journey[0]] : null;
      const manual = hit && o.not_recovered.includes(journey?.[0]);
      const back = rec != null ? `, back ${rec} s after restart` : "";
      const verdict = !hit ? "it kept working" : manual ? 'it went down <span class="miss">until a manual restart</span>' : `it went down${back}`;
      const agree = hit === listed ? "" : ` <span class="miss">${listed ? "graph expected an outage" : "not in this view"}</span>`;
      return `<li><b>${esc(o.target)}</b> stopped for 60 s: ${verdict}${agree}</li>`;
    })
    .filter(Boolean);
  if (!rows.length) return "";
  return `<h3>Outage tests on the running shop</h3><ul class="tests">${rows.join("")}</ul>`;
}

function drawDetail() {
  const { graph, view, selected } = state;
  const f = state.fns.find((x) => x.name === selected);
  const p = profile(graph, view, selected);
  const deps = new Set(p ? p.components : []);
  const parts = [`<h2><span class="swatch" style="background:${LINE[selected] || "#333"}"></span>${esc(selected)}</h2>`];
  parts.push(`<p class="lede">${esc(f.description || "")} Promise: <b>${minutes(f.promise)}</b>${f.critical ? ", critical" : ""}.</p>`);
  if (!p || !p.slowest) {
    parts.push(`<p>No dependency in the ${VIEW_LABEL[view].toLowerCase()} view.</p>`);
  } else {
    const s = p.slowest;
    const c = p.longest;
    parts.push(`<div class="facts">
      <div><h3>Slowest link</h3><p class="big${s.recovery > f.promise ? " late" : ""}">${esc(s.component)} · ${minutes(s.recovery)}</p>${stationList(s.names, s.component)}</div>
      <div><h3>Restore chain</h3><p class="big${c.chain > f.promise ? " late" : ""}">${minutes(c.chain)}</p>
        <p class="note">Restore order, dependencies first:</p>${stationList([...c.names].reverse(), s.component)}</div>
      <div><h3>Depends on ${deps.size}</h3><p class="list">${[...deps].sort().map(esc).join(", ")}</p></div>
    </div>`);
  }
  if (view !== "plan") {
    const gaps = graph.rows(graph.queries.plan_gaps[view]).find((g) => g.function === selected);
    if (gaps && gaps.missing.length) {
      parts.push(`<h3>Left out of the plan's own list</h3><p class="list">${gaps.missing
        .map((m) => `${esc(m.component)} (${minutes(m.recovery_min)})`)
        .join(", ")}</p>`);
    }
  }
  parts.push(testsFor(selected, deps));
  parts.push(`<details><summary>The Cypher this view runs</summary><pre>${esc(graph.queries.profile[view].trim())}</pre></details>`);
  $("#detail").innerHTML = parts.join("");
}

function select(name) {
  state.selected = name;
  writeUrl();
  drawMap();
  drawDetail();
}

function setView(view) {
  state.view = view;
  document.querySelectorAll("#views button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.view === view)));
  $("#view-note").textContent = VIEW_NOTE[view];
  writeUrl();
  drawMap();
  drawDetail();
}

// --- what-if and guard ----------------------------------------------------------------------------------------------

function runWhatIf() {
  const notice = $("#notice").value.trim();
  if (!notice) return;
  const r = whatIf(state.graph, notice, state.view);
  if (!r.components.length) {
    $("#whatif-out").innerHTML = "<p>No component of the plan matches this notice.</p>";
    return;
  }
  const comps = r.components
    .map((c) => `${esc(c.component)} <span class="how">(${c.how === "named" ? "named" : `search score ${c.score}`})</span>`)
    .join(", ");
  const out = r.outage_min != null ? minutes(r.outage_min) : "not stated, so each component's recovery time";
  const items = r.affected
    .map((a) => `<li class="${a.broken ? "late" : ""}"><b>${a.broken ? "Broken" : "Kept"}</b> ${esc(a.function)}: promises ${minutes(a.promise_min)}, out ${minutes(a.expected_outage_min)}</li>`)
    .join("");
  $("#whatif-out").innerHTML = `<p>Components: ${comps}. Expected outage: ${out}.</p>
    <ul class="impact">${items || "<li>No function depends on it in this view.</li>"}</ul>
    <h3>Restore order</h3>${stationList(r.restore_order, null)}`;
}

function fillGuard() {
  const names = state.graph.rows("MATCH (c:Service|Datastore|Queue) RETURN c.name AS n ORDER BY n").map((r) => r.n);
  const opts = (sel) => names.map((n) => `<option${n === sel ? " selected" : ""}>${esc(n)}</option>`).join("");
  $("#g-source").innerHTML = opts("frontend");
  $("#g-target").innerHTML = opts("product-catalog");
  $("#g-function").innerHTML = state.fns
    .map((f) => `<option${f.name === "Browse the shop" ? " selected" : ""}>${esc(f.name)}</option>`)
    .join("");
}

function runGuard() {
  const source = $("#g-source").value;
  const target = $("#g-target").value;
  const fn = $("#g-function").value;
  if (source === target) {
    $("#guard-out").innerHTML = "<p>Pick two different components.</p>";
    return;
  }
  const r = simulateCall(state.graph, source, target, [fn], "evidence");
  const what = (f) => (f.check === "inversions" ? "slowest link" : "restore chain");
  const items = [
    ...r.new.map((f) => `<li class="late"><b>New</b> ${esc(f.function)}: promises ${minutes(f.promise)}, ${what(f)} ${minutes(f.value)}${stationList(f.names, f.component)}</li>`),
    ...r.worse.map((f) => `<li class="late"><b>Worse</b> ${esc(f.function)}: ${what(f)} ${minutes(f.was)} → ${minutes(f.value)}${stationList(f.names, f.component)}</li>`),
  ];
  $("#guard-out").innerHTML = items.length
    ? `<p>${esc(source)} → ${esc(target)} for ${esc(fn)} would break:</p><ul class="impact">${items.join("")}</ul>`
    : `<p>${esc(source)} → ${esc(target)} for ${esc(fn)}: no promise breaks or gets worse.</p>`;
}

// --- measured results -----------------------------------------------------------------------------------------------

function drawResults() {
  const t = state.tests;
  if (!t) return;
  const stops = t.outcomes.filter((o) => o.kind === "stop");
  const fnNames = t.functions;
  const pred = t.predictions || {};
  const head = `<tr><th scope="col" class="corner">Component stopped</th>${fnNames.map((f) => `<th scope="col" class="fn"><span class="vname">${esc(f)}</span><span class="swatch" style="background:${LINE[f] || "#333"}"></span></th>`).join("")}</tr>`;
  const body = stops
    .map((o) => {
      const cells = fnNames
        .map((f) => {
          if (o.unjudged.includes(f)) return '<td class="na" title="not judged">·</td>';
          const hit = o.affected.includes(f);
          const said = (pred[o.test] || []).includes(f);
          const cls = hit ? (said ? "hit ok" : "hit miss") : said ? "free miss" : "free";
          return `<td class="${cls}" title="${esc(f)}: ${hit ? "stopped" : "kept working"}${said === hit ? "" : said ? " (expected an outage)" : " (not expected)"}">${hit ? "●" : ""}</td>`;
        })
        .join("");
      return `<tr><th scope="row">${esc(o.target)}</th>${cells}</tr>`;
    })
    .join("");
  $("#results-table").innerHTML = `<thead>${head}</thead><tbody>${body}</tbody>`;
  $("#results-legend").innerHTML = `<li><span class="key">●</span> the function went down</li>
    <li><span class="key miss-key"></span> the evidence view, frozen before the test, said otherwise</li>
    <li><span class="key">·</span> no order reached the back office in the window, so it is not judged</li>`;
  const views = t.views?.stop || {};
  $("#results-scores").innerHTML = VIEWS.filter((v) => views[v])
    .map((v) => {
      const s = views[v].score;
      return `<li><b>${VIEW_LABEL[v]}</b>: ${s.tp} of ${s.tp + s.fn} function outages predicted, ${s.fp} false alarms, ${s.exact} of ${s.tests} tests exactly right</li>`;
    })
    .join("");
}

// --- start ----------------------------------------------------------------------------------------------------------

async function start() {
  try {
    state.graph = await Graph.load();
  } catch (err) {
    $("#status").textContent = `Relate could not start in this browser: ${err.message}`;
    return;
  }
  const counts = state.graph.rows("MATCH (n) RETURN count(n) AS n")[0].n;
  const rels = state.graph.rows("MATCH ()-[r]->() RETURN count(r) AS n")[0].n;
  $("#status").textContent = `Relate ${RELATE_VERSION} running in this tab (WebAssembly): ${counts} nodes, ${rels} relationships, loaded in ${state.graph.loadMs} ms.`;
  state.fns = functions(state.graph);
  try {
    const tests = await fetch("data/tests.json").then((r) => (r.ok ? r.json() : null));
    if (tests) {
      const predictions = await fetch("data/predictions.json").then((r) => (r.ok ? r.json() : null));
      if (predictions) tests.predictions = Object.fromEntries(predictions.faults.map((f) => [f.id, f.predicted.evidence]));
      state.tests = tests;
    }
  } catch {
    state.tests = null;
  }
  state.view = read("view", "evidence", VIEWS);
  state.selected = read("function", "Place an order", state.fns.map((f) => f.name));
  document.querySelectorAll("#views button").forEach((b) => b.addEventListener("click", () => setView(b.dataset.view)));
  $("#examples").innerHTML = EXAMPLES.map((e, i) => `<button type="button" data-i="${i}">${esc(e)}</button>`).join("");
  $("#examples").querySelectorAll("button").forEach((b) =>
    b.addEventListener("click", () => {
      $("#notice").value = EXAMPLES[Number(b.dataset.i)];
      runWhatIf();
    }),
  );
  $("#run-whatif").addEventListener("click", runWhatIf);
  fillGuard();
  $("#run-guard").addEventListener("click", runGuard);
  setView(state.view);
  drawResults();
  document.body.classList.add("ready");
}

start();
