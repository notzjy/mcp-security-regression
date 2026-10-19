from __future__ import annotations

import os
import time

import httpx

from .models import Case, Check
from .rules import evaluate_response, verdict
from .storage import Store, new_id, now

MAX_RESPONSE_BYTES = 512_000


async def run_suite(store: Store, target_id: str, suite_id: str, campaign_id: str | None = None) -> dict:
    target = store.target(target_id)
    suite = store.get("suite", suite_id)
    run = {
        "id": new_id("run"), "target": target.model_dump(), "suite_id": suite_id,
        "suite_hash": suite["hash"], "oracle_version": suite["oracle_version"],
        "started_at": now(), "finished_at": None, "status": "running", "results": [],
        "campaign_id": campaign_id,
    }
    store.put("run", run)
    headers = {"Accept": "application/json"}
    if target.auth_env:
        secret = os.getenv(target.auth_env)
        if not secret:
            run.update(status="error", error=f"Missing environment variable {target.auth_env}", finished_at=now())
            store.put("run", run)
            raise ValueError(run["error"])
        headers["Authorization"] = f"Bearer {secret}"
    try:
        async with httpx.AsyncClient(timeout=target.timeout_seconds, follow_redirects=False, trust_env=False) as client:
            for raw_case in suite["cases"]:
                case = Case.model_validate(raw_case)
                result = {"case_id": case.id, "title": case.title, "category": case.category, "checks": [], "steps": []}
                if case.requires_sessions and not target.supports_sessions:
                    result["checks"].append(Check(rule="session_capability", status="review", detail="Target declares no session support; isolation is unverified").model_dump())
                else:
                    for index, step in enumerate(case.steps):
                        # A fresh namespace on every execution prevents fixture contamination.
                        request_body = {target.text_field: step.text, target.session_field: f"{run['id']}:{case.id}:{step.session}", target.user_field: step.user}
                        trace_id = f"{run['id']}:{case.id}:{index}"
                        evidence = {"index": index, "trace_id": trace_id, "request": request_body, "url": target.base_url + target.endpoint}
                        started = time.perf_counter()
                        try:
                            async with client.stream("POST", evidence["url"], json=request_body, headers={**headers, "X-Eval-Trace-Id": trace_id, "X-Eval-Run-Id": run["id"]}) as response:
                                chunks = bytearray()
                                async for chunk in response.aiter_bytes():
                                    chunks.extend(chunk)
                                    if len(chunks) > MAX_RESPONSE_BYTES:
                                        raise ValueError("Response exceeds 512 KB evidence limit")
                                raw = bytes(chunks).decode("utf-8", errors="replace")
                            try:
                                body = __import__("json").loads(raw)
                            except ValueError:
                                body = None
                            evidence.update(status_code=response.status_code, response_body=body, response_text=raw)
                            checks = evaluate_response(case, step, target, response.status_code, body, raw)
                        except (httpx.HTTPError, ValueError) as exc:
                            evidence.update(error=f"{type(exc).__name__}: {str(exc)[:500]}")
                            checks = [Check(rule="transport", status="error", detail=evidence["error"])]
                        evidence["latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
                        evidence["checks"] = [c.model_dump() for c in checks]
                        result["steps"].append(evidence)
                        result["checks"].extend(evidence["checks"])
                result["status"] = verdict(result["checks"])
                run["results"].append(result)
                store.put("run", run)
        run.update(status="completed", finished_at=now())
        run["counts"] = {s: sum(r["status"] == s for r in run["results"]) for s in ("pass", "fail", "review", "error")}
        return store.put("run", run)
    except BaseException as exc:
        run.update(status="error", error=f"{type(exc).__name__}: execution interrupted", finished_at=now())
        store.put("run", run)
        raise


def compare_runs(store: Store, baseline_id: str, candidate_id: str) -> dict:
    before, after = store.get("run", baseline_id), store.get("run", candidate_id)
    if before["status"] != "completed" or after["status"] != "completed":
        raise ValueError("Only completed runs can be compared")
    if before["suite_hash"] != after["suite_hash"]:
        raise ValueError("Regression comparison requires exactly the same frozen suite hash")
    compatibility_fields = ("text_field", "session_field", "user_field", "issues_field", "trace_field", "supports_sessions", "supports_trace")
    if any(before["target"][k] != after["target"][k] for k in compatibility_fields):
        raise ValueError("Adapter/capability changes require a new baseline")
    old = {r["case_id"]: r for r in before["results"]}
    if set(old) != {r["case_id"] for r in after["results"]}:
        raise ValueError("Case identities differ")
    rows = []
    for result in after["results"]:
        previous, current = old[result["case_id"]]["status"], result["status"]
        if "error" in (previous, current):
            change = "inconclusive"
        elif previous == "pass" and current == "fail":
            change = "new_failure"
        elif previous == "fail" and current == "pass":
            change = "fixed"
        elif previous != current:
            change = "needs_review"
        else:
            change = "unchanged"
        rows.append({"case_id": result["case_id"], "title": result["title"], "before": previous, "after": current, "change": change})
    return {"baseline_id": baseline_id, "candidate_id": candidate_id, "suite_hash": before["suite_hash"], "baseline_version": before["target"]["version"], "candidate_version": after["target"]["version"], "counts": {s: sum(r["change"] == s for r in rows) for s in ("new_failure", "fixed", "unchanged", "needs_review", "inconclusive")}, "cases": rows}
