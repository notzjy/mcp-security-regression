# Third-party components

本仓库业务代码使用 MIT 许可证。依赖包保留各自许可证，不包含重命名或伪造的第三方框架。

- [lastmile-ai/mcp-agent](https://github.com/lastmile-ai/mcp-agent)：Apache-2.0；本项目使用其 MCPApp、Agent、OpenAIAugmentedLLM 和工具调用循环。
- [modelcontextprotocol/python-sdk](https://github.com/modelcontextprotocol/python-sdk)：MIT；使用其 ClientSession、stdio transport、mcp.server.fastmcp.FastMCP。
- [FastAPI](https://github.com/fastapi/fastapi)、[Pydantic](https://github.com/pydantic/pydantic)、[HTTPX](https://github.com/encode/httpx)、[Uvicorn](https://github.com/encode/uvicorn)：各自上游许可证。

版本见 requirements.lock。FastMCP 指 MCP Python SDK 内置服务端类，本项目不依赖独立的 `fastmcp` 2.x 包，也不把 MCP 协议声称为自行发明。
