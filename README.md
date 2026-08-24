# 大学生职场适应智能体

V0.2 全栈实现：React 前端、FastAPI 模块化单体后端，以及可审计的工具运行时。

本版本新增 DeepSeek 原生 Tool Calling、Tavily 联网搜索、来源追溯、日历事件草稿、工具目录与调用审计。联网搜索未配置时会明确返回不可用，不会伪造实时结果。

## 本地开发

```bash
pnpm install
pnpm dev
```

前端默认运行在 <http://localhost:5173>，并请求
`http://localhost:8000/api/v1`。需修改后端地址时，复制 `apps/web/.env.example`
为 `apps/web/.env` 并设置 `VITE_API_BASE_URL`。

## 后端开发

```powershell
cd apps/api
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
Copy-Item .env.example .env
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

接口文档位于 <http://localhost:8000/docs>。业务数据持久化到 MySQL；未配置 DeepSeek Key 时，后端自动使用演示回复。

启用联网搜索时，在 `apps/api/.env` 设置 `TAVILY_API_KEY`。对话中的时效性问题会由 DeepSeek 选择 `web.search`，前端会显示工具执行状态和可点击来源。也可通过 `GET /api/v1/tools` 查看工具目录，或调用 `POST /api/v1/tools/web.search:invoke` 进行独立验证。

## 质量检查

```bash
pnpm format:check
pnpm typecheck
pnpm build
```

后端检查：

```powershell
cd apps/api
ruff check app tests
pytest
```

前端已完成真实 API 联调，包括账号认证、SSE 流式对话、记忆、知识库和行动计划。
