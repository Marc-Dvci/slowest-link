"""Turn exported traces into observed calls between components, scoped to the function each trace serves.

Input: Jaeger's JSON trace format (`/api/traces`). A trace's root span names the user journey (the shop's load
generator opens one span per task, such as `user_checkout_single`); the plan maps journeys to functions.

- A span whose parent runs in another component is a call from that component to this one.
- A client span to a database or a producer or consumer span to a queue is a call to that datastore or queue (these
  components export no spans of their own).
- A producer does not wait for its consumers: its call to the queue is asynchronous. Work below a consumer span serves
  the function that enters at the consumer (the order goes to accounting), not the journey that produced the message.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

DB_SYSTEMS = {"postgresql": "astronomy-db", "postgres": "astronomy-db", "redis": "valkey-cart", "valkey": "valkey-cart"}
QUEUE_SYSTEMS = {"kafka": "kafka"}


@dataclass
class ObservedCall:
    source: str
    target: str
    mode: str  # "sync" or "async"
    journeys: set[str] = field(default_factory=set)
    calls: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "mode": self.mode,
            "journeys": sorted(self.journeys),
            "calls": self.calls,
        }


@dataclass
class Derivation:
    calls: list[ObservedCall]
    traces: int
    attributed: int
    unattributed_roots: dict[str, int]
    unknown_targets: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "traces": self.traces,
            "attributed": self.attributed,
            "unattributed_roots": dict(sorted(self.unattributed_roots.items())),
            "unknown_targets": dict(sorted(self.unknown_targets.items())),
            "calls": [call.to_dict() for call in self.calls],
        }


def _tags(span: Mapping[str, Any]) -> dict[str, Any]:
    return {tag["key"]: tag.get("value") for tag in span.get("tags") or []}


def _parent_id(span: Mapping[str, Any]) -> str | None:
    for ref in span.get("references") or []:
        if ref.get("refType") in ("CHILD_OF", "FOLLOWS_FROM"):
            return str(ref["spanID"])
    return None


def _peer(tags: Mapping[str, Any], components: set[str]) -> str | None:
    """The component a client, producer or consumer span talks to, when that component exports no spans."""
    system = str(tags.get("db.system.name") or tags.get("db.system") or "").lower()
    if system in DB_SYSTEMS:
        return DB_SYSTEMS[system]
    messaging = str(tags.get("messaging.system") or "").lower()
    if messaging in QUEUE_SYSTEMS:
        return QUEUE_SYSTEMS[messaging]
    address = str(tags.get("server.address") or tags.get("net.peer.name") or tags.get("peer.service") or "")
    return address if address in components else None


class _Serves:
    """The function a span serves: the trace root's, unless a consumer span above it hands the work to the function
    that enters at the consumer. Walks up the parents iteratively and remembers every answer."""

    def __init__(
        self,
        spans: Mapping[str, Mapping[str, Any]],
        service: Mapping[str, str],
        consumer_function: Mapping[str, str],
        root_function: str,
    ) -> None:
        self.spans, self.service, self.consumers, self.root = spans, service, consumer_function, root_function
        self.memo: dict[str, str] = {}

    def __call__(self, sid: str) -> str:
        chain: list[str] = []
        current: str | None = sid
        result = self.root
        while current is not None and current in self.spans:
            if current in self.memo:
                result = self.memo[current]
                break
            chain.append(current)
            if _tags(self.spans[current]).get("span.kind") == "consumer" and self.service[current] in self.consumers:
                result = self.consumers[self.service[current]]
                break
            current = _parent_id(self.spans[current])
        for item in chain:
            self.memo[item] = result
        return result


def derive_calls(
    traces: Iterable[Mapping[str, Any]],
    journey_to_function: Mapping[str, str],
    consumer_function: Mapping[str, str],
    components: set[str],
) -> Derivation:
    """Derive observed calls from Jaeger traces.

    journey_to_function: root span name -> function name (from the plan).
    consumer_function: component -> the function that enters there (for work below a consumer span).
    components: the component names the plan knows; spans from other services are not components.
    """
    edges: dict[tuple[str, str], ObservedCall] = {}
    unattributed: dict[str, int] = defaultdict(int)
    unknown: dict[str, int] = defaultdict(int)
    count = attributed = 0

    def record(source: str, target: str, mode: str, function: str) -> None:
        call = edges.setdefault((source, target), ObservedCall(source, target, mode))
        if mode == "sync":
            call.mode = "sync"  # a call that is synchronous anywhere is synchronous
        call.journeys.add(function)
        call.calls += 1

    for trace in traces:
        count += 1
        processes = trace.get("processes") or {}
        spans = {str(s["spanID"]): s for s in trace.get("spans") or []}
        service = {sid: processes.get(s.get("processID"), {}).get("serviceName", "") for sid, s in spans.items()}
        roots = [s for sid, s in spans.items() if _parent_id(s) not in spans]
        if not roots:
            continue
        root = min(roots, key=lambda s: s.get("startTime", 0))
        root_id = str(root["spanID"])
        function = journey_to_function.get(str(root.get("operationName")))
        if function is None and service[root_id] in consumer_function:
            # A consumer that starts its own trace (linked, not parented, to the producer) serves its own function.
            function = consumer_function[service[root_id]]
        if function is None:
            unattributed[str(root.get("operationName"))] += 1
            continue
        attributed += 1

        children: dict[str, list[str]] = defaultdict(list)
        for sid, span in spans.items():
            parent_id = _parent_id(span)
            if parent_id is not None:
                children[parent_id].append(sid)
        serves = _Serves(spans, service, consumer_function, function)

        for sid, span in spans.items():
            here = service[sid]
            if here not in components:
                continue
            tags = _tags(span)
            kind = tags.get("span.kind")
            parent = _parent_id(span)
            if parent in spans and service[parent] != here and service[parent] in components:
                # Cross-component edge into this span. A consumer span's parent is the producer: the consumer
                # depends on the queue, not on the producer, so that hop is recorded below instead.
                if kind != "consumer":
                    record(service[parent], here, "sync", serves(sid))
            if kind in ("client", "producer", "consumer"):
                peer = _peer(tags, components)
                if peer is None:
                    if kind == "client" and not any(service[c] != here for c in children[sid]):
                        name = str(
                            tags.get("server.address") or tags.get("net.peer.name") or tags.get("rpc.service") or ""
                        )
                        if name:
                            unknown[name] += 1
                    continue
                if peer == here:
                    continue
                record(here, peer, "async" if kind == "producer" else "sync", serves(sid))

    calls = sorted(edges.values(), key=lambda c: (c.source, c.target))
    return Derivation(calls, count, attributed, dict(unattributed), dict(unknown))
