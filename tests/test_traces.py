"""Trace derivation on hand-built Jaeger traces, one behaviour per test."""

from __future__ import annotations

from typing import Any

from slowest_link.traces import derive_calls

COMPONENTS = {"proxy", "web", "orders", "db", "cache", "queue", "ledger", "fraud"}
JOURNEYS = {"user_order": "Place order", "user_view": "View product"}
CONSUMERS = {"ledger": "Record orders", "fraud": "Screen orders"}


def span(
    sid: str, process: str, op: str, parent: str | None = None, kind: str = "server", **tags: Any
) -> dict[str, Any]:
    refs = [{"refType": "CHILD_OF", "spanID": parent}] if parent else []
    tag_list = [{"key": "span.kind", "value": kind}] + [
        {"key": k.replace("_", "."), "value": v} for k, v in tags.items()
    ]
    return {"spanID": sid, "operationName": op, "references": refs, "startTime": int(sid[1:]), "processID": process,
            "tags": tag_list}  # fmt: skip


def trace(*spans: dict[str, Any]) -> dict[str, Any]:
    services = {s["processID"] for s in spans}
    return {"traceID": "t", "processes": {p: {"serviceName": p} for p in services}, "spans": list(spans)}


def derive(*traces: dict[str, Any]) -> dict[tuple[str, str], Any]:
    result = derive_calls(traces, JOURNEYS, CONSUMERS, COMPONENTS)
    return {(c.source, c.target): c for c in result.calls}


def test_a_span_whose_parent_runs_elsewhere_is_a_call() -> None:
    calls = derive(
        trace(
            span("s1", "loadgen", "user_order", kind="internal"),
            span("s2", "proxy", "ingress", "s1"),
            span("s3", "web", "GET /api", "s2"),
        )
    )
    assert set(calls) == {("proxy", "web")}  # the load generator is a client, not a component
    assert calls["proxy", "web"].journeys == {"Place order"}
    assert calls["proxy", "web"].mode == "sync"


def test_a_database_client_span_is_a_call_to_the_database() -> None:
    calls = derive(
        trace(
            span("s1", "loadgen", "user_view", kind="internal"),
            span("s2", "web", "GET", "s1"),
            span("s3", "web", "SELECT", "s2", kind="client", db_system_name="postgresql"),
        )
    )
    # The peer name comes from the database system: postgresql maps to the shop's astronomy-db.
    assert ("web", "astronomy-db") in calls


def test_a_producer_span_is_an_asynchronous_call_to_the_queue() -> None:
    calls = derive(
        trace(
            span("s1", "loadgen", "user_order", kind="internal"),
            span("s2", "orders", "PlaceOrder", "s1"),
            span("s3", "orders", "orders publish", "s2", kind="producer", messaging_system="kafka"),
        )
    )
    assert calls["orders", "kafka"].mode == "async"


def test_work_below_a_consumer_serves_the_consumers_function() -> None:
    calls = derive(
        trace(
            span("s1", "loadgen", "user_order", kind="internal"),
            span("s2", "orders", "PlaceOrder", "s1"),
            span("s3", "orders", "publish", "s2", kind="producer", messaging_system="kafka"),
            span("s4", "ledger", "receive", "s3", kind="consumer", messaging_system="kafka"),
            span("s5", "ledger", "INSERT", "s4", kind="client", db_system="postgresql"),
        )
    )
    assert calls["ledger", "kafka"].journeys == {"Record orders"}
    assert calls["ledger", "kafka"].mode == "sync"
    assert calls["ledger", "astronomy-db"].journeys == {"Record orders"}
    assert ("orders", "ledger") not in calls  # a consumer depends on the queue, not on the producer


def test_a_consumer_that_starts_its_own_trace_serves_its_own_function() -> None:
    result = derive_calls(
        [trace(span("s1", "fraud", "receive orders", kind="consumer", messaging_system="kafka"))],
        JOURNEYS,
        CONSUMERS,
        COMPONENTS,
    )
    assert result.attributed == 1
    assert {(c.source, c.target, frozenset(c.journeys)) for c in result.calls} == {
        ("fraud", "kafka", frozenset({"Screen orders"}))
    }


def test_a_call_seen_synchronously_anywhere_is_synchronous() -> None:
    t1 = trace(
        span("s1", "loadgen", "user_order", kind="internal"),
        span("s2", "orders", "x", "s1"),
        span("s3", "orders", "p", "s2", kind="producer", messaging_system="kafka"),
    )
    t2 = trace(
        span("s1", "fraud", "receive", kind="consumer", messaging_system="kafka"),
    )
    t3 = trace(
        span("s1", "loadgen", "user_order", kind="internal"),
        span("s2", "orders", "x", "s1"),
        span("s3", "orders", "c", "s2", kind="consumer", messaging_system="kafka"),
    )
    calls = derive(t1, t2, t3)
    assert calls["orders", "kafka"].mode == "sync"
    assert calls["orders", "kafka"].calls == 2


def test_traces_from_unknown_journeys_are_counted_not_used() -> None:
    result = derive_calls(
        [trace(span("s1", "loadgen", "browser_change_currency", kind="internal"), span("s2", "web", "GET", "s1"))],
        JOURNEYS,
        CONSUMERS,
        COMPONENTS,
    )
    assert result.calls == []
    assert result.unattributed_roots == {"browser_change_currency": 1}


def test_a_client_call_to_a_peer_outside_the_plan_is_reported() -> None:
    result = derive_calls(
        [
            trace(
                span("s1", "loadgen", "user_view", kind="internal"),
                span("s2", "web", "GET", "s1"),
                span("s3", "web", "GET", "s2", kind="client", server_address="payments.example"),
            )
        ],
        JOURNEYS,
        CONSUMERS,
        COMPONENTS,
    )
    assert result.unknown_targets == {"payments.example": 1}


def test_a_client_span_answered_by_an_instrumented_service_is_not_unknown() -> None:
    result = derive_calls(
        [
            trace(
                span("s1", "loadgen", "user_view", kind="internal"),
                span("s2", "web", "GET", "s1"),
                span("s3", "web", "call", "s2", kind="client", server_address="orders-host"),
                span("s4", "orders", "serve", "s3"),
            )
        ],
        JOURNEYS,
        CONSUMERS,
        COMPONENTS,
    )
    assert result.unknown_targets == {}
    assert [(c.source, c.target) for c in result.calls] == [("web", "orders")]


def test_counts_and_journeys_accumulate_across_traces() -> None:
    def one(journey: str) -> dict[str, Any]:
        return trace(
            span("s1", "loadgen", journey, kind="internal"),
            span("s2", "proxy", "in", "s1"),
            span("s3", "web", "x", "s2"),
        )

    calls = derive(one("user_order"), one("user_view"), one("user_view"))
    assert calls["proxy", "web"].calls == 3
    assert calls["proxy", "web"].journeys == {"Place order", "View product"}


def test_an_empty_trace_is_counted_and_skipped() -> None:
    result = derive_calls([{"traceID": "x", "processes": {}, "spans": []}], JOURNEYS, CONSUMERS, COMPONENTS)
    assert (result.traces, result.attributed, result.calls) == (1, 0, [])
