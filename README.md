# 大学生职场适应智能体

V0.3 全栈实现：React 前端、FastAPI 模块化单体后端、资料收件箱与可追溯成长闭环。

本版本在 V0.2 工具运行时基础上新增会议录音/截图/文档/Excel 接收、隐私脱敏、纪要与行动项草稿、周报/月报草稿、能力证据和个性化学习路线。Excel 支持 XLSX、XLS 和 CSV，读取工作表、表头与有限行数作为可追溯摘要。对话支持添加图片、音频、文档和表格附件；图片附件由 GLM 视觉模型理解，明确的图片生成请求由 GLM-Image 处理，其他内容继续使用文本模型。所有派生内容保留来源；未配置对应模型能力时会明确报错，不会伪造识别结果。

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

启用图片理解与图片生成时，在 `apps/api/.env` 设置 `BIGMODEL_API_KEY`。默认由 `glm-5v-turbo` 理解图片，由 `glm-image` 生成图片；模型名可分别通过 `BIGMODEL_VISION_MODEL` 和 `BIGMODEL_IMAGE_MODEL` 调整。

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
