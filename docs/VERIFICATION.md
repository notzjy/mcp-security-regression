# 交付验证

本文件记录实际执行结果，区分应用夹具、协议夹具与真实模型服务。

## 已执行

- 在 CPython 3.12.14 / Linux x86_64 安装并导入真实的 `mcp-agent 0.2.6`、`mcp 1.30.0`、`openai 1.109.1`；`pip check` 没有依赖冲突。
- CLI 演示实际启动独立 Uvicorn HTTP 子进程与独立 MCP stdio 子进程，进行初始化、工具发现、真实 HTTP 请求和 SQLite 保存。
- 同一 suite hash：`0b7a90229dc90b8ccaeaf58d480aeadcc23f4a07d99a80e819ee4d8e0e756eba`。
- 每个版本 6 条 case、7 次 HTTP 请求。漏洞版 4 fail / 2 pass，修复版 6 pass，退化版 1 fail / 5 pass；比较得到修复 4 项、新增失败 1 项。
- 证据见 `examples/verified-demo/summary.json`、三个原始运行 JSON/HTML 和两个版本比较 JSON。文件由实际执行器生成。
- 22 项自动化测试全部通过；原始 JUnit 结果见本目录 `test-results.xml`，覆盖规则、冻结用例、真实 HTTP/MCP、Web API、模型调用协议、工具权限与两轮反馈交接。
- 工作台 API 通过实际监听端口验证：运行演示、获取状态、版本比较、原始证据、下载 HTML 报告、再次执行固定用例、MCP 审计。
- 前端 JavaScript 进行语法检查。交付环境没有可启动的 Chromium，下载也未获得有效浏览器包，所以没有伪造工作台截图或声称完成浏览器渲染测试。

## 多 Agent 验证的含义

`tests/test_agents.py` **真的使用第三方 mcp-agent 创建两个 Agent**，由框架发送 Chat Completions 请求、处理工具调用、启动角色绑定的 MCP Server，并完成两轮交接。用例执行仍请求真实的本地 HTTP 服务。

其中“模型服务”是本地脚本实现的 OpenAI 协议夹具，目的仅为可重复验证框架 API、MCP 工具发现、权限、持久化与反馈闭环。脚本不具备大模型理解能力，其返回内容已显式标记为协议夹具。它只位于 tests 中，正常项目代码不会调用或自动回退到它。

因此：调用链及业务执行已经验证；**在线大模型的推理、工具遵循率与评测分析质量尚未实测**。这部分需由使用者填写 API Key、模型名和可选供应商地址后执行 `guardbench collaborate`。项目没有内置真实密钥。

## 未声称已执行的事项

- 未对任何第三方线上应用执行安全扫描；报告仅针对包内受控应用夹具。
- 未把这些通过率当成模型安全能力的科研结论。
- 未在交付环境启动 Docker 引擎，未在用户 GitHub 上触发 Actions；对应配置供用户后续运行。
- 未实现多人登录、生产部署、分布式队列或通用任意业务断言；当前范围见 README。

## 自行复现

```bash
python -m pip install -r requirements.lock
python -m pip install --no-deps -e .
python -m pip check
python -m pytest -q
guardbench demo
```

验证结果随真实执行产生，运行 ID、时间戳、端口和耗时会不同。固定用例内容哈希及受控场景的判定应一致。
