from __future__ import annotations

import os
from importlib.resources import files
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import Field

from .catalog import make_suite
from .demo import execute_demo
from .demo_app import router
from .mcp_client import call, evaluation_client
from .models import Candidate, StrictModel, Target
from .report import html_report
from .storage import Store
from .workflow import run_campaign


class ExecuteRequest(StrictModel):
    target_id: str
    suite_id: str


class FreezeRequest(StrictModel):
    candidates: list[Candidate] = Field(default_factory=list, max_length=3)


class CampaignRequest(StrictModel):
    baseline_target: str
    candidate_target: str
    rounds: int = Field(default=1, ge=1, le=2)


def create_app(store: Store | None = None) -> FastAPI:
    store = store or Store()
    app = FastAPI(title="GuardBench · MCP 安全回归", version="0.1.0")
    app.include_router(router)

    @app.middleware("http")
    async def origin_guard(request: Request, call_next):
        origin = request.headers.get("origin")
        if origin and urlsplit(origin).netloc != request.headers.get("host"):
            return JSONResponse({"detail": "Cross-origin access is not enabled"}, status_code=403)
        return await call_next(request)

    @app.exception_handler(ValueError)
    async def value_error(request: Request, exc: ValueError):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(KeyError)
    async def key_error(request: Request, exc: KeyError):
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @app.get("/", response_class=HTMLResponse)
    def index():
        return files("guardbench").joinpath("static/index.html").read_text(encoding="utf-8")

    @app.get("/api/state")
    def state():
        return {"targets": store.list("target"), "suites": store.list("suite"), "runs": [{k: v for k, v in r.items() if k != "results"} for r in store.list("run")], "campaigns": store.list("campaign"), "llm_configured": bool(os.getenv("OPENAI_API_KEY")), "model": os.getenv("GUARDBENCH_MODEL", "gpt-4o-mini")}

    @app.post("/api/targets")
    def register_target(target: Target):
        return store.put("target", target.model_dump())

    @app.post("/api/suites")
    def freeze_suite(data: FreezeRequest):
        suite = make_suite(data.candidates)
        return store.put("suite", suite, immutable=True)

    @app.post("/api/runs")
    async def execute(data: ExecuteRequest):
        async with evaluation_client(store) as session:
            return await call(session, "run_suite", target_id=data.target_id, suite_id=data.suite_id)

    @app.get("/api/runs/{identity}")
    def get_run(identity: str):
        return store.get("run", identity)

    @app.get("/api/runs/{identity}/report", response_class=HTMLResponse)
    def get_report(identity: str):
        return HTMLResponse(html_report(store.get("run", identity)), headers={"Content-Disposition": f'attachment; filename="{store.get("run", identity)["id"]}.html"'})

    @app.get("/api/compare")
    async def comparison(baseline_id: str, candidate_id: str):
        async with evaluation_client(store) as session:
            return await call(session, "compare_runs", baseline_id=baseline_id, candidate_id=candidate_id)

    @app.get("/api/audit")
    def audit(campaign_id: str | None = None):
        return store.audits(campaign_id)

    @app.post("/api/demo")
    async def demo(request: Request):
        # This URL is chosen by the local server's configured port, not by an Agent.
        host, port = request.scope.get("server", ("127.0.0.1", 8000))
        return await execute_demo(store, f"http://127.0.0.1:{port}")

    @app.post("/api/campaigns")
    async def collaborate(data: CampaignRequest):
        try:
            return await run_campaign(store, data.baseline_target, data.candidate_target, data.rounds)
        except ValueError:
            raise
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"{type(exc).__name__}: 模型协作未完成；查看 campaign 状态和本地终端。不会回退到伪造结果。") from exc

    return app


app = create_app()
