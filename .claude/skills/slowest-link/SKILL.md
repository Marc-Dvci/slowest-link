---
name: slowest-link
description: Check recovery promises against what each function really depends on. Use when asked whether a business function can meet its recovery time (RTO), what an outage or a status-page notice breaks, what order to restore in, which dependencies a continuity plan misses, or before adding a call from one service to another.
---

# Slowest Link

The continuity plan is a Relate graph in `plan/` (a Markdown vault: one note per function, component and test).

- A **function** (`Function`) is a user journey or back-office job with a recovery promise, `promise_min`.
- A **component** (`Service`, `Datastore`, `Queue`) has the recovery time its owner declared, `recovery_min`.
- A **call** (`CALLS`) records whether the published architecture declares it (`declared`), whether traces show it
  (`observed`), for which functions (`journeys`), whether the caller waits (`mode`: `sync` or `async`), and which
  functions an outage test proved survive without it (`survives_without`).
- A **test** (`Test`) is an outage test on the running system, linked to the component it stopped (`EXERCISED`).

## Tools (MCP server `slowest-link`)

| Question | Tool |
|---|---|
| Which promises are broken, and why? | `check_promises(view)` |
| Why is this function at risk? | `explain_function(function)` |
| A provider or a component is down: what breaks, and what comes back first? | `what_if(notice)` |
| Will this new call between services break a promise? | `check_new_call(source, target, functions)` |
| Anything else about the graph | `get_schema()`, then `read_cypher(query)` (read-only) |

Without the MCP server, the same answers come from the command line: `python -m slowest_link check`,
`explain "<function>"`, `whatif "<notice>"`, `guard --call "<source>-><target>" --for "<function>"`.

## Rules

1. Use the **evidence** view unless asked otherwise, and name the view in the answer. The plan view repeats the plan's
   own list; the architecture view follows every declared call and overstates what a function needs.
2. Every number you write (minutes, counts, paths) comes from a tool result in this conversation. Never compute a
   recovery time yourself; quote the tool.
3. Give the path that explains each finding, from the function's entry point to the slow component.
4. Before writing code that adds a network call from one service to another, call `check_new_call`. If it reports a
   new or worse finding, tell the user before making the change.
5. The plan is read-only through these tools. To change a promise or a recovery time, edit the note in `plan/` and
   let a person review the diff.

## Example

> Our managed PostgreSQL is down, restore expected in 3 hours. What breaks?

Call `what_if` with the notice. Report the broken promises first, each with its promise and the expected outage, then
the restore order the tool returns.
