# Slowest Link: system card

## Who it is for, and what it is for

Slowest Link is for the people who own a business continuity plan: the continuity lead who signs the recovery test
plan, the engineer on call during an outage, and the developer whose change adds a dependency. It answers three
questions about the plan: which recovery promises the dependencies make impossible, what an outage notice breaks and in
what order to restore, and whether a planned call between services breaks a promise.

## Uses it is built for

- Checking a plan before its yearly recovery test, and choosing what to test.
- Reading an outage notice against the plan during an incident.
- Gating changes in CI and in a coding agent's loop.

Its findings feed a person's decision. The plan stays under the team's control: every tool opens it read-only, and
changes to promises and recovery times are made in the notes and reviewed as diffs.

## Models and data

| Component | Model or source | Role |
|---|---|---|
| Checks, what-if, guard | Cypher on Relate by Neo4j 1.2.0 | Decide every finding |
| Notice matching | Relate full-text index and `SEARCH` | Map free text to components |
| Agents | Any MCP client (Claude Code, Cursor, Codex and others) | Ask questions, explain the tools' answers |
| Agent evaluation | Qwen 3.8 Flash, Alibaba Cloud Model Studio | Measure answers with and without the graph |
| System | OpenTelemetry Astronomy Shop 3.1.0 | Real services, traces and outage tests |
| Plan inputs | `sources/` | Promises, the plan's component lists, recovery objectives |

## Evaluation

- The checks are deterministic Cypher; their figures on the running shop are in [`RESULTS.md`](RESULTS.md): from 20
  component stops, the evidence view predicted 39 of 40 outages with 4 false alarms.
- The browser code gives the command line's answers on 28 of 28 cases ([`web/test/parity.mjs`](../web/test/parity.mjs)).
- Agents: Qwen 3.8 Flash answered 12 questions three times each. Reading the plan's notes: 36 of 36 correct, 85 seconds
  per answer. Calling the tools: 31 of 36 correct, 21 seconds per answer.

## Human oversight

- People own the promises and the recovery objectives; the vault records who owns each component.
- Trace evidence and test results are written as properties on the notes, so a reviewer sees each change as a diff.
- The guard blocks a change in CI; a person decides whether to change the code or the promise.
- An agent connected over MCP reads the plan and cannot write to it.

## How a correction is made

Edit the note in `plan/` (a promise, a recovery objective, a component list) and open a pull request. The plan guard
reports what the change does to every promise, and the reviewer approves the diff. Evidence is refreshed by
re-importing traces (`import-traces`) and recording new tests (`record-tests`).
