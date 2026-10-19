from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from .catalog import make_suite
from .demo import execute_demo, local_demo_server, seed_demo
from .mcp_client import call, evaluation_client
from .models import Candidate, Target
from .report import export_run
from .storage import Store
from .workflow import run_campaign


def emit(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


async def dispatch(args, store: Store) -> int:
    if args.command == "demo":
        with local_demo_server() as base:
            emit(await execute_demo(store, base, args.output))
    elif args.command == "add-target":
        target = Target.model_validate_json(Path(args.file).read_text(encoding="utf-8"))
        emit(store.put("target", target.model_dump()))
    elif args.command == "seed-demo":
        emit(seed_demo(store, args.base_url))
    elif args.command == "freeze":
        candidates = [] if not args.candidates else [Candidate.model_validate(c) for c in json.loads(Path(args.candidates).read_text(encoding="utf-8"))]
        if len(candidates) > 3:
            raise ValueError("At most 3 supplementary candidates")
        emit(store.put("suite", make_suite(candidates), immutable=True))
    elif args.command == "list":
        emit(store.list(args.kind))
    elif args.command == "run":
        async with evaluation_client(store) as session:
            result = await call(session, "run_suite", target_id=args.target, suite_id=args.suite)
        emit(result)
        export_run(store, result["run_id"], args.output)
    elif args.command == "compare":
        async with evaluation_client(store) as session:
            result = await call(session, "compare_runs", baseline_id=args.baseline, candidate_id=args.candidate)
        emit(result)
        if args.fail_on_regression:
            if result["counts"]["new_failure"]:
                return 2
            if result["counts"]["inconclusive"] or result["counts"]["needs_review"]:
                return 3
    elif args.command == "collaborate":
        emit(await run_campaign(store, args.baseline, args.candidate, args.rounds))
    elif args.command == "report":
        emit(export_run(store, args.run, args.output))
    return 0


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description="GuardBench · MCP 安全回归评测")
    parser.add_argument("--db", default=os.getenv("GUARDBENCH_DB", "data/guardbench.sqlite3"))
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="启动本地工作台")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    demo = sub.add_parser("demo", help="真实 MCP+HTTP 受控演示，无模型调用")
    demo.add_argument("--output", default="artifacts/demo")
    target = sub.add_parser("add-target")
    target.add_argument("file")
    seed = sub.add_parser("seed-demo", help="注册长期运行的本地示例服务")
    seed.add_argument("--base-url", default="http://127.0.0.1:8000")
    freeze = sub.add_parser("freeze")
    freeze.add_argument("--candidates")
    ls = sub.add_parser("list")
    ls.add_argument("kind", choices=["target", "suite", "run", "campaign"])
    run = sub.add_parser("run")
    run.add_argument("--target", required=True)
    run.add_argument("--suite", required=True)
    run.add_argument("--output", default="artifacts/runs")
    compare = sub.add_parser("compare")
    compare.add_argument("--baseline", required=True)
    compare.add_argument("--candidate", required=True)
    compare.add_argument("--fail-on-regression", action="store_true")
    agent = sub.add_parser("collaborate", help="真实 mcp-agent 双 Agent 模型协作")
    agent.add_argument("--baseline", required=True)
    agent.add_argument("--candidate", required=True)
    agent.add_argument("--rounds", type=int, choices=[1, 2], default=1)
    report = sub.add_parser("report")
    report.add_argument("--run", required=True)
    report.add_argument("--output", default="artifacts/runs")
    args = parser.parse_args()
    os.environ["GUARDBENCH_DB"] = str(Path(args.db).resolve())
    store = Store(args.db)
    if args.command == "serve":
        import uvicorn
        from .web import create_app
        uvicorn.run(create_app(store), host=args.host, port=args.port)
        return
    try:
        code = asyncio.run(dispatch(args, store))
    except (ValueError, KeyError, RuntimeError) as exc:
        parser.exit(1, f"错误：{exc}\n")
    raise SystemExit(code)


if __name__ == "__main__":
    main()
