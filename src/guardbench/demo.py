from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import httpx

from .catalog import make_suite
from .mcp_client import call, evaluation_client
from .models import Target
from .report import export_comparison, export_run
from .storage import Store


def seed_demo(store: Store, base_url: str) -> dict:
    for version in ("vulnerable", "fixed", "regressed"):
        target = Target(id=f"demo_{version}", name=f"受控示例 · {version}", version=version, base_url=base_url, endpoint=f"/demo/{version}/proofread", model_config_snapshot={"fixture": True, "uses_llm": False})
        store.put("target", target.model_dump())
    suite = make_suite()
    store.put("suite", suite, immutable=True)
    return suite


@contextmanager
def local_demo_server():
    # Ask the OS for a free port, then start a real HTTP server in a child process.
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    process = subprocess.Popen([sys.executable, "-m", "uvicorn", "guardbench.demo_server:app", "--host", "127.0.0.1", "--port", str(port), "--log-level", "error"], stdout=subprocess.DEVNULL)
    try:
        with httpx.Client(trust_env=False, timeout=0.3) as client:
            for _ in range(100):
                if process.poll() is not None:
                    raise RuntimeError("Demo HTTP server exited during startup")
                try:
                    if client.get(base + "/health").status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.05)
            else:
                raise RuntimeError("Demo HTTP server failed to start")
        yield base
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


async def execute_demo(store: Store, base_url: str, output: str | Path = "artifacts/demo") -> dict:
    suite = seed_demo(store, base_url)
    run_ids = {}
    async with evaluation_client(store) as session:
        discovered = await session.list_tools()
        for version in ("vulnerable", "fixed", "regressed"):
            result = await call(session, "run_suite", target_id=f"demo_{version}", suite_id=suite["id"])
            run_ids[version] = result["run_id"]
        fixed_comparison = await call(session, "compare_runs", baseline_id=run_ids["vulnerable"], candidate_id=run_ids["fixed"])
        regression = await call(session, "compare_runs", baseline_id=run_ids["fixed"], candidate_id=run_ids["regressed"])
    dest = Path(output)
    dest.mkdir(parents=True, exist_ok=True)
    for identity in run_ids.values():
        export_run(store, identity, dest)
    export_comparison(store, run_ids["vulnerable"], run_ids["fixed"], dest / "fix-comparison.json")
    export_comparison(store, run_ids["fixed"], run_ids["regressed"], dest / "regression-comparison.json")
    summary = {"mode": "deterministic_demo", "uses_llm": False, "transport": "real MCP stdio + real HTTP", "suite_id": suite["id"], "suite_hash": suite["hash"], "mcp_tools": [t.name for t in discovered.tools], "runs": run_ids, "counts": {v: store.get("run", identity)["counts"] for v, identity in run_ids.items()}, "fixes": fixed_comparison["counts"], "regression": regression["counts"]}
    (dest / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary
