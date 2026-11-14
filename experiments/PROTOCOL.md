# Experiment protocol

The experiments run the OpenTelemetry Astronomy Shop 3.1.0 (images `ghcr.io/open-telemetry/demo:3.1.0-*`) with its
standard compose files: `compose.yaml`, `compose.full.yaml`, `compose.observability.yaml` and `compose.extras.yaml`.
Each step's raw output is committed under `evidence/`.

## Order

1. **Plan frozen.** The plan's inputs (`sources/`) are committed before the shop first runs.
2. **E0, traces.** The healthy shop runs under its own load generator. Traces are exported from Jaeger, and each call
   between components is recorded with the journeys whose traces contain it.
3. **Predictions frozen.** For every fault in E1 and E2, each view of the graph (plan, architecture, evidence)
   predicts which journeys it reaches. The predictions are committed before E1 and E2 run.
4. **E1, stop tests.** Each component is stopped for a fixed window, then started again.
5. **E2, flag tests.** Each failure flag that targets a running service is turned on for a fixed window, then off.
6. **Score.** Each (fault, journey) pair is compared: predicted reached against measured affected.

## Measuring a journey

A prober replays each user journey of the shop's load generator through the front door (`http://localhost:8080`), at
a fixed rate, and records the status and latency of every request. A journey attempt fails when any of its requests
returns an error status or times out (10 s).

A journey is **affected** in a fault window when, compared with the baseline window just before it:

- its failure rate is at least 20 percentage points higher, or
- its 95th-percentile latency is at least twice the baseline and above 1 second.

The journeys are the shop's load generator tasks, with the same requests: `user_index`, `user_browse_product`,
`user_add_to_cart`, `user_view_cart`, `user_checkout_single`, `user_get_recommendations` and `user_get_ads`, one per
function of the plan. Checkout runs every 2 seconds, the others every second. The shop's own load generator is
stopped during E1 and E2, so the prober's traffic is the only traffic.

## Measuring the back-office functions

"Record orders in accounting" and "Screen orders for fraud" serve the orders the prober places. For each window, an
order placed in it counts as served when its id appears in the accounting ledger (`accounting.order` in
`astronomy-db`) or in the fraud detection log, checked 90 seconds after the test ends. The function is affected when
its served share is at least 20 percentage points below the baseline window's. A window in which no order was placed
cannot be judged, and that pair is left out of the score.

## Timings

- Stop tests: 40 s baseline, 60 s with the component stopped, then up to 180 s of recovery.
- Flag tests: 40 s baseline, 60 s with the flag on (the variant in `flags.csv`), then 60 s with it off.
- Between tests, every journey must succeed 10 times in a row before the next baseline starts.

## Recovery

After a stopped component starts again, the prober keeps running. A journey's **recovery time** is the time from the
start command to its first run of 5 consecutive successful attempts. A journey that has not recovered after 180
seconds is recorded as not recovered on its own; the app services are then restarted so the next test starts healthy,
and the restart is recorded.

## Faults

- E1 stops each of the plan's 20 components.
- E2 turns on the 14 failure flags in `flags.csv`. Each row names the component where the shop's code injects the
  fault. The flags file's other entries are left out: two target the agent service, which this compose set does not
  run, one controls telemetry content, and one makes the load generator flood the home page.
