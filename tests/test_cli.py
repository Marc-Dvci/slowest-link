"""The command line and the MCP tools, through their entry points, on copies of the committed plan."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from slowest_link import cli
from slowest_link.mcp_server import build_server

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.integration


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    copy = tmp_path / "plan"
    shutil.copytree(ROOT / "plan", copy, ignore=shutil.ignore_patterns("*.cypherlite.writer"))
    return copy


def run(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, str]:
    code = cli.main(list(args))
    return code, capsys.readouterr().out


def test_check_prints_every_view(vault: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = run(capsys, "check", "--vault", str(vault), "--as-of", "2026-11-14")
    assert code == 0
    for label in ("Plan (", "Architecture (", "Evidence ("):
        assert label in out


def test_check_json_is_machine_readable(vault: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = run(capsys, "check", "--vault", str(vault), "--json")
    data = json.loads(out)
    assert code == 0 and set(data["inversions"]) == {"plan", "architecture", "evidence"}


def test_check_can_fail_a_build_on_a_broken_promise(vault: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(capsys, "check", "--vault", str(vault), "--fail-on-inversion")[0] == 1
    assert run(capsys, "check", "--vault", str(vault), "--fail-on-inversion", "--fail-view", "plan")[0] == 0


def test_explain_shows_a_function_in_each_view(vault: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = run(capsys, "explain", "View cart", "--vault", str(vault))
    assert code == 0 and "restore chain" in out and "Evidence" in out


def test_whatif_reads_a_notice(vault: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = run(capsys, "whatif", "PostgreSQL database down for 3 hours", "--vault", str(vault), "--json")
    data = json.loads(out)
    assert code == 0 and data["outage_min"] == 180
    assert data["components"][0]["component"] == "astronomy-db"


def test_guard_blocks_a_call_that_breaks_a_promise(vault: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = run(
        capsys, "guard", "--vault", str(vault), "--call", "frontend->product-catalog", "--for", "Browse the shop"
    )
    assert code == 1 and "NEW" in out and "Browse the shop" in out


def test_guard_lets_a_harmless_call_through(vault: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = run(capsys, "guard", "--vault", str(vault), "--call", "cart->flagd", "--for", "View cart")
    assert code == 0 and "No promise breaks" in out


def test_guard_refuses_an_unknown_component(vault: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(capsys, "guard", "--vault", str(vault), "--call", "frontend->ghost")[0] == 2


def test_guard_needs_exactly_one_kind_of_change(vault: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(capsys, "guard", "--vault", str(vault))[0] == 2


def test_guard_compares_two_versions_of_the_plan(vault: Path, capsys: pytest.CaptureFixture[str]) -> None:
    note = vault / "Service" / "frontend.md"
    text = note.read_text(encoding="utf-8")
    planned = (
        "CALLS:\n  - declared: true\n    mode: sync\n    journeys:\n      - Browse the shop\n"
        '    target: "[[Service/product-catalog]]"\n'
    )
    note.write_text(text.replace("CALLS:\n", planned, 1), encoding="utf-8")
    code, out = run(capsys, "guard", "--vault", str(vault), "--base", str(ROOT / "plan"))
    assert code == 1 and "frontend -> product-catalog for Browse the shop" in out


def test_the_hook_ignores_edits_outside_the_plan(
    vault: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    import io

    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"tool_input": {"file_path": str(ROOT / "README.md")}})))
    assert run(capsys, "guard", "--vault", str(vault), "--hook", "--call", "frontend->product-catalog")[0] == 0


def test_predict_writes_every_fault_for_every_view(vault: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "p.json"
    assert run(capsys, "predict", "--vault", str(vault), "--out", str(out))[0] == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert len(data["faults"]) == 34
    assert all(set(f["predicted"]) == {"plan", "architecture", "evidence"} for f in data["faults"])


def test_export_writes_the_pages_data(vault: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(capsys, "export", "--vault", str(vault), "--out-dir", str(tmp_path / "data"))[0] == 0
    assert (tmp_path / "data" / "graph.cypher").read_text(encoding="utf-8").startswith("CREATE ")
    assert "evidence" in json.loads((tmp_path / "data" / "queries.json").read_text(encoding="utf-8"))["profile"]


def test_seed_and_import_rebuild_the_plan_from_its_sources(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    fresh = tmp_path / "plan"
    assert run(capsys, "seed", "--vault", str(fresh))[0] == 0
    code, out = run(capsys, "import-traces", "--vault", str(fresh), "--date", "2026-11-14")
    counts = json.loads(out)
    assert code == 0 and counts == {"traces": 1037, "attributed": 1037, "confirmed": 24, "added": 0}


@pytest.mark.anyio
async def test_the_mcp_server_offers_the_checks_as_tools(vault: Path) -> None:
    server = build_server(vault)
    names = {tool.name for tool in await server.list_tools()}
    assert names == {
        "list_functions",
        "check_promises",
        "explain_function",
        "what_if",
        "check_new_call",
        "get_schema",
        "read_cypher",
    }


def test_the_mcp_cypher_tool_refuses_writes(vault: Path) -> None:
    server = build_server(vault)
    tool = {t.name: t for t in server._tool_manager.list_tools()}["read_cypher"]  # noqa: SLF001
    result = tool.fn(query="CREATE (:Intruder)")
    assert "error" in result and "read-only" in result["error"]


def test_the_mcp_what_if_tool_answers_from_the_graph(vault: Path) -> None:
    server = build_server(vault)
    tool = {t.name: t for t in server._tool_manager.list_tools()}["what_if"]  # noqa: SLF001
    result = tool.fn(notice="kafka is down for 3 hours")
    assert result["outage_min"] == 180 and result["components"][0]["component"] == "kafka"
