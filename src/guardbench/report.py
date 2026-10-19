import html
import json
from pathlib import Path

from .runner import compare_runs
from .storage import Store


def html_report(run: dict) -> str:
    esc = html.escape
    content = [f"<h1>GuardBench · {esc(run['id'])}</h1>", f"<p>版本：{esc(run['target']['version'])} · 用例哈希：<code>{esc(run['suite_hash'])}</code></p>", f"<p>确定性判定：{esc(json.dumps(run.get('counts', {})))}</p>", "<p>pass 仅表示已执行的合同规则通过；review 为证据不足；error 为执行未完成。模型解释不改变判定。</p>"]
    for result in run["results"]:
        content.append(f"<section><h2>{esc(result['case_id'])} · {esc(result['title'])} · {esc(result['status'])}</h2>")
        for check in result["checks"]:
            content.append(f"<p><b>{esc(check['rule'])} [{esc(check['status'])}]</b> {esc(check['detail'])}</p>")
        content.append(f"<details><summary>原始请求 / 响应 / trace 证据</summary><pre>{esc(json.dumps(result['steps'], ensure_ascii=False, indent=2))}</pre></details></section>")
    return "<!doctype html><html lang='zh-CN'><meta charset='utf-8'><title>GuardBench 实测报告</title><style>body{font:15px system-ui;max-width:1100px;margin:40px auto;padding:0 20px;color:#203449;background:#f5f7fa}section{background:white;border:1px solid #d9e1e8;border-radius:10px;padding:20px;margin:18px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere}code{overflow-wrap:anywhere}h2{font-size:20px}</style>" + "".join(content) + "</html>"


def export_run(store: Store, run_id: str, directory: str | Path) -> dict:
    run = store.get("run", run_id)
    dest = Path(directory)
    dest.mkdir(parents=True, exist_ok=True)
    json_path, html_path = dest / f"{run_id}.json", dest / f"{run_id}.html"
    json_path.write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")
    html_path.write_text(html_report(run), encoding="utf-8")
    return {"json": str(json_path), "html": str(html_path)}


def export_comparison(store: Store, baseline_id: str, candidate_id: str, path: str | Path) -> dict:
    data = compare_runs(store, baseline_id, candidate_id)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data
