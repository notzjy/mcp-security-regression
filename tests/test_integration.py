import json

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

from guardbench.catalog import make_suite
from guardbench.demo import execute_demo, seed_demo
from guardbench.demo_server import app as demo_app
from guardbench.mcp_client import call, evaluation_client
from guardbench.models import Candidate, Target
from guardbench.report import html_report
from guardbench.runner import compare_runs, run_suite
from guardbench.web import create_app

from conftest import http_server


async def test_full_demo_real_stdio_and_http(store, tmp_path):
    with http_server(demo_app) as base:
        summary = await execute_demo(store, base, tmp_path / "reports")
    assert summary["uses_llm"] is False
    assert summary["counts"]["vulnerable"] == {"pass": 2, "fail": 4, "review": 0, "error": 0}
    assert summary["counts"]["fixed"]["pass"] == 6
    assert summary["fixes"]["fixed"] == 4
    assert summary["regression"]["new_failure"] == 1
    for identity in summary["runs"].values():
        run = store.get("run", identity)
        assert sum(len(r["steps"]) for r in run["results"]) == 7
        assert all(s["trace_id"].startswith(identity) for r in run["results"] for s in r["steps"])
        assert (tmp_path / "reports" / f"{identity}.html").exists()
    assert any(e["tool"] == "run_suite" for e in store.audits())


async def test_suite_integrity_and_comparison_guard(store):
    with http_server(demo_app) as base:
        core = seed_demo(store, base)
        other = make_suite([Candidate(template_id="injection", text="different input", rationale="test")])
        store.put("suite", other, immutable=True)
        first = await run_suite(store, "demo_fixed", core["id"])
        second = await run_suite(store, "demo_fixed", other["id"])
    with pytest.raises(ValueError, match="same frozen suite hash"):
        compare_runs(store, first["id"], second["id"])
    mutated = dict(core, cases=[])
    with pytest.raises(ValueError, match="Immutable"):
        store.put("suite", mutated, immutable=True)
    store.put("suite", mutated)
    with pytest.raises(ValueError, match="integrity"):
        store.get("suite", core["id"])


async def test_network_failure_is_not_security_finding(store):
    suite = make_suite()
    store.put("suite", suite)
    store.put("target", Target(id="offline", name="offline", version="v1", base_url="http://127.0.0.1:1", timeout_seconds=.1).model_dump())
    result = await run_suite(store, "offline", suite["id"])
    assert result["counts"]["error"] == 6
    assert result["counts"]["fail"] == 0


async def test_missing_capabilities_and_html_injection(store):
    app = FastAPI()
    @app.post("/proofread")
    def endpoint():
        return {"issues": [], "message": "<script>alert('xss')</script>"}
    with http_server(app) as base:
        suite = seed_demo(store, base)
        store.put("target", Target(id="limited", name="limited", version="1", base_url=base, supports_sessions=False, supports_trace=False).model_dump())
        result = await run_suite(store, "limited", suite["id"])
    assert result["counts"]["review"] == 2
    rendered = html_report(result)
    assert "<script>alert" not in rendered
    assert "&lt;script&gt;" in rendered


async def test_web_registration_reports_and_origin_guard(store):
    app = create_app(store)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        assert (await client.get("/")).status_code == 200
        assert "GuardBench" in (await client.get("/")).text
        response = await client.post("/api/targets", json={"id": "t", "name": "t", "version": "1", "base_url": "http://127.0.0.1:9"})
        assert response.status_code == 200
        assert (await client.post("/api/suites", json={})).status_code == 200
        assert len((await client.get("/api/state")).json()["targets"]) == 1
        blocked = await client.post("/api/suites", json={}, headers={"Origin": "https://other.example"})
        assert blocked.status_code == 403


async def test_repeat_runs_have_isolated_fixture_namespaces(store):
    with http_server(demo_app) as base:
        suite = seed_demo(store, base)
        a = await run_suite(store, "demo_vulnerable", suite["id"])
        b = await run_suite(store, "demo_vulnerable", suite["id"])
    assert a["id"] != b["id"]
    assert a["counts"] == b["counts"]
    assert compare_runs(store, a["id"], b["id"])["counts"]["new_failure"] == 0


async def test_compare_marks_errors_inconclusive(store):
    with http_server(demo_app) as base:
        suite = seed_demo(store, base)
        before = await run_suite(store, "demo_fixed", suite["id"])
    target = store.target("demo_fixed").model_copy(update={"base_url": "http://127.0.0.1:1", "timeout_seconds": .1})
    store.put("target", target.model_dump())
    after = await run_suite(store, target.id, suite["id"])
    assert compare_runs(store, before["id"], after["id"])["counts"]["inconclusive"] == 6


async def test_workbench_end_to_end_real_web_api_mcp_and_http(store, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # Exercise the same endpoints used by the page, on a real listening socket.
    with http_server(create_app(store)) as base:
        async with httpx.AsyncClient(base_url=base, timeout=90, trust_env=False) as client:
            demo = await client.post("/api/demo")
            assert demo.status_code == 200, demo.text
            data = demo.json()
            state = (await client.get("/api/state")).json()
            assert len(state["targets"]) == 3 and len(state["runs"]) == 3
            baseline, candidate = data["runs"]["fixed"], data["runs"]["regressed"]
            comparison = await client.get("/api/compare", params={"baseline_id": baseline, "candidate_id": candidate})
            assert comparison.json()["counts"]["new_failure"] == 1
            evidence = (await client.get(f"/api/runs/{candidate}")).json()
            assert any(s["response_text"] == "TEST_DONE" for r in evidence["results"] for s in r["steps"])
            report = await client.get(f"/api/runs/{candidate}/report")
            assert report.status_code == 200 and "attachment" in report.headers["content-disposition"]
            assert "output_schema" in report.text
            rerun = await client.post("/api/runs", json={"target_id": "demo_fixed", "suite_id": data["suite_id"]})
            assert rerun.json()["counts"]["pass"] == 6
            audit = (await client.get("/api/audit")).json()
            assert any(event["tool"] == "run_suite" for event in audit)
