"""Replay the shop's user journeys through its front door and record every attempt.

The journeys are the tasks of the shop's own load generator (`src/load-generator/locustfile.py` in the
OpenTelemetry demo), with the same requests and payloads. Each journey runs in its own thread at a fixed period. Every
attempt is one JSON line: journey, start time, success, latency, the failing status, and the order id for checkouts.
"""

from __future__ import annotations

import http.cookiejar
import json
import random
import threading
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PRODUCTS = [
    "0PUK6V6EV0",
    "1YMWWN1N4O",
    "2ZYFJ3GM2N",
    "66VCHSJNUP",
    "6E92ZMYYFZ",
    "9SIQT8TOJO",
    "L9ECAV7KIM",
    "LS4PSXUNUM",
    "OLJCESPC7Z",
    "HQTGWGPNH4",
]
CATEGORIES = ["binoculars", "telescopes", "accessories", "assembly", "travel", "books", None]
TIMEOUT_S = 10.0
PEOPLE = json.loads((Path(__file__).with_name("people.json")).read_text(encoding="utf-8"))


class JourneyFailed(Exception):
    def __init__(self, status: str) -> None:
        super().__init__(status)
        self.status = status


class Client:
    """One visitor: a cookie jar and the shop's base URL, as Locust's HttpUser keeps them."""

    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def request(self, method: str, path: str, body: Any = None) -> Any:
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.base + path, data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with self.opener.open(req, timeout=TIMEOUT_S) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            raise JourneyFailed(f"{method} {path.split('?')[0]} {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            raise JourneyFailed(f"{method} {path.split('?')[0]} {type(exc).__name__}") from exc
        try:
            return json.loads(raw) if raw else None
        except ValueError:
            return None


def index(c: Client, rng: random.Random) -> dict[str, Any]:
    c.request("GET", "/")
    return {}


def browse_product(c: Client, rng: random.Random) -> dict[str, Any]:
    c.request("GET", "/api/products/" + rng.choice(PRODUCTS))
    return {}


def get_recommendations(c: Client, rng: random.Random) -> dict[str, Any]:
    c.request("GET", "/api/recommendations?productIds=" + rng.choice(PRODUCTS))
    return {}


def get_ads(c: Client, rng: random.Random) -> dict[str, Any]:
    category = rng.choice(CATEGORIES)
    c.request("GET", "/api/data/?contextKeys=" + str(category))
    return {}


def view_cart(c: Client, rng: random.Random) -> dict[str, Any]:
    c.request("GET", "/api/cart")
    return {}


def add_to_cart(c: Client, rng: random.Random, user: str = "") -> dict[str, Any]:
    user = user or str(uuid.uuid1())
    product = rng.choice(PRODUCTS)
    c.request("GET", "/api/products/" + product)
    c.request(
        "POST",
        "/api/cart",
        {"item": {"productId": product, "quantity": rng.choice([1, 2, 3, 4, 5, 10])}, "userId": user},
    )
    return {}


def checkout(c: Client, rng: random.Random) -> dict[str, Any]:
    user = str(uuid.uuid1())
    add_to_cart(c, rng, user)
    person = dict(rng.choice(PEOPLE))
    person["userId"] = user
    result = c.request("POST", "/api/checkout", person)
    order_id = result.get("orderId") if isinstance(result, dict) else None
    return {"order_id": order_id}


JOURNEYS: dict[str, tuple[Callable[..., dict[str, Any]], float]] = {
    "user_index": (index, 1.0),
    "user_browse_product": (browse_product, 1.0),
    "user_get_recommendations": (get_recommendations, 1.0),
    "user_get_ads": (get_ads, 1.0),
    "user_view_cart": (view_cart, 1.0),
    "user_add_to_cart": (add_to_cart, 1.0),
    "user_checkout_single": (checkout, 2.0),
}


@dataclass
class Prober:
    base: str
    out: Path
    seed: int = 7
    stop: threading.Event = field(default_factory=threading.Event)
    lock: threading.Lock = field(default_factory=threading.Lock)
    records: list[dict[str, Any]] = field(default_factory=list)

    def _run(self, name: str, fn: Callable[..., dict[str, Any]], period: float, index_: int) -> None:
        rng = random.Random(self.seed * 100 + index_)
        client = Client(self.base)
        with self.out.open("a", encoding="utf-8") as sink:
            while not self.stop.is_set():
                started = time.time()
                record: dict[str, Any] = {"journey": name, "t": round(started, 3)}
                try:
                    record.update(fn(client, rng))
                    record["ok"] = True
                except JourneyFailed as exc:
                    record["ok"] = False
                    record["status"] = exc.status
                record["latency_s"] = round(time.time() - started, 3)
                with self.lock:
                    sink.write(json.dumps(record) + "\n")
                    sink.flush()
                    self.records.append(record)
                self.stop.wait(max(0.0, period - (time.time() - started)))

    def start(self) -> list[threading.Thread]:
        threads = [
            threading.Thread(target=self._run, args=(name, fn, period, i), daemon=True, name=name)
            for i, (name, (fn, period)) in enumerate(JOURNEYS.items())
        ]
        for thread in threads:
            thread.start()
        return threads


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8080")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--seconds", type=float, default=20)
    a = ap.parse_args()
    prober = Prober(a.base, a.out)
    prober.start()
    time.sleep(a.seconds)
    prober.stop.set()
    time.sleep(TIMEOUT_S + 1)
