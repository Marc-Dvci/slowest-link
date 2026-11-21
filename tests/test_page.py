"""The browser page, driven in a real Chromium: Relate's WebAssembly build loads the plan in the tab, and every section
of the demo path answers. Run with `python -m pytest -m e2e` after `playwright install chromium` and `npm ci` in web/
(axe-core comes from web/node_modules)."""

from __future__ import annotations

import functools
import http.server
import socketserver
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Page, sync_playwright

pytestmark = pytest.mark.e2e
WEB = Path(__file__).resolve().parents[1] / "web"
AXE = WEB / "node_modules" / "axe-core" / "axe.min.js"


@pytest.fixture(scope="module")
def base_url() -> Iterator[str]:
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(WEB))
    handler.log_message = lambda *a, **k: None  # type: ignore[method-assign]
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}/index.html"
    httpd.shutdown()


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        yield b
        b.close()


@pytest.fixture
def page(browser: Any, base_url: str) -> Iterator[Page]:
    pg = browser.new_page(viewport={"width": 1280, "height": 900})
    pg.goto(f"{base_url}?view=evidence&function=Place%20an%20order")
    pg.wait_for_selector("body.ready", timeout=60_000)
    yield pg
    pg.close()


def test_relate_runs_in_the_tab_and_draws_every_function(page: Page) -> None:
    assert page.inner_text("#status").startswith("Relate 1.2.0 running in this tab (WebAssembly): 63 nodes")
    assert page.locator("#map .row").count() == 9


@pytest.mark.parametrize(("view", "broken"), [("plan", 0), ("architecture", 5), ("evidence", 4)])
def test_each_view_states_how_many_functions_miss_their_promise(page: Page, view: str, broken: int) -> None:
    page.click(f"#views button[data-view={view}]")
    assert page.get_attribute(f"#views button[data-view={view}]", "aria-pressed") == "true"
    assert f"{broken} of 9 functions cannot be restored within their promise" in page.inner_text("#map-summary")


def test_clicking_a_line_opens_that_function_and_keeps_it_in_the_link(page: Page) -> None:
    page.click('#map .row[data-fn="View cart"]')
    detail = page.inner_text("#detail")
    assert detail.startswith("View cart")
    assert "1 h 30 min" in detail  # its restore chain, past the 1-hour promise
    assert "function=View+cart" in page.url


def test_a_link_opens_the_view_and_function_it_names(browser: Any, base_url: str) -> None:
    pg = browser.new_page()
    pg.goto(f"{base_url}?view=plan&function=Show%20ads")
    pg.wait_for_selector("body.ready", timeout=60_000)
    assert pg.get_attribute("#views button[data-view=plan]", "aria-pressed") == "true"
    assert pg.inner_text("#detail").startswith("Show ads")
    pg.close()


def test_an_outage_notice_lists_the_broken_promises_and_the_restore_order(page: Page) -> None:
    page.click("#examples button >> nth=0")  # "Our managed PostgreSQL database is down. Estimated restore: 3 hours."
    out = page.inner_text("#whatif-out")
    assert out.startswith("Components: astronomy-db")
    assert "Expected outage: 3 h" in out
    assert out.count("Broken") == 3
    assert page.locator("#whatif-out .stops li").first.inner_text() == "astronomy-db"


def test_a_notice_that_matches_nothing_says_so(page: Page) -> None:
    page.fill("#notice", "The coffee machine on the third floor is out of order.")
    page.click("#run-whatif")
    assert page.inner_text("#whatif-out") == "No component of the plan matches this notice."


def test_the_guard_reports_a_call_that_breaks_browse_the_shop(page: Page) -> None:
    page.click("#run-guard")  # frontend -> product-catalog for Browse the shop, preselected
    out = page.inner_text("#guard-out")
    assert "New Browse the shop: promises 1 h, slowest link 4 h" in out
    assert "New Browse the shop: promises 1 h, restore chain 5 h" in out


def test_the_guard_refuses_a_call_from_a_component_to_itself(page: Page) -> None:
    page.select_option("#g-target", "frontend")
    page.click("#run-guard")
    assert page.inner_text("#guard-out") == "Pick two different components."


def test_the_results_grid_shows_the_one_outage_the_evidence_view_missed(page: Page) -> None:
    assert "Evidence: 39 of 40 outages predicted, 4 false alarms" in page.inner_text("#results-scores")
    missed = page.locator("#results-table td.hit.miss")
    assert missed.count() == 1
    assert missed.first.get_attribute("title") == "Place an order: stopped (not expected)"


def test_the_page_has_no_serious_accessibility_violation(page: Page) -> None:
    page.click("#examples button >> nth=0")
    page.click("#run-guard")
    page.add_script_tag(path=str(AXE))
    result = page.evaluate("axe.run(document, { resultTypes: ['violations'] })")
    serious = [(v["id"], len(v["nodes"])) for v in result["violations"] if v["impact"] in ("serious", "critical")]
    assert serious == []
