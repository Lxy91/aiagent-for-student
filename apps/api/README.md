# Workplace Agent API

FastAPI 模块化单体后端，使用 SQLAlchemy 2、Alembic 与 MySQL 8 持久化业务数据。

## 启动

```powershell
cd apps/api
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
Copy-Item .env.example .env
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

Swagger 文档：<http://localhost:8000/docs>

## MySQL

本机需先创建数据库和专用用户。以管理员账户进入 MySQL 后执行：

```sql
CREATE DATABASE workplace_agent CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE USER 'workplace_agent'@'localhost' IDENTIFIED BY '请替换为强密码';
GRANT ALL PRIVILEGES ON workplace_agent.* TO 'workplace_agent'@'localhost';
FLUSH PRIVILEGES;
```

在 `.env` 中填写：

```dotenv
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=workplace_agent
MYSQL_PASSWORD=你的数据库密码
MYSQL_DATABASE=workplace_agent
```

应用使用 `mysql+asyncmy` 驱动。`GET /api/v1/ready` 会执行数据库探活；连接失败时不会错误地报告就绪。

## DeepSeek

将真实密钥写入 `apps/api/.env`：

```dotenv
DEEPSEEK_API_KEY=sk-your-key
DEEPSEEK_MODEL=deepseek-v4-flash
DEMO_MODE=false
```

密钥只由后端读取，不得写入 React 的 `VITE_*` 变量。

## 当前接口

- `GET /api/v1/health`、`GET /api/v1/ready`
- `POST /api/v1/auth/register`、`POST /api/v1/auth/login`
- `POST /api/v1/conversations`、`GET /api/v1/conversations`
- `GET /api/v1/conversations/{id}/messages`
- `POST /api/v1/conversations/{id}/messages:stream`
- `GET /api/v1/memories`、`PATCH/DELETE /api/v1/memories/{id}`
- `POST /api/v1/memory-candidates`
- `POST /api/v1/memory-candidates/{id}:confirm`
- `GET/POST /api/v1/knowledge/documents`
- `GET /api/v1/knowledge/documents/{id}`
- `GET /api/v1/plans`
- `POST /api/v1/plans:draft`
- `POST /api/v1/plan-drafts/{id}:confirm`
- `PATCH /api/v1/tasks/{id}`


## Agent 执行轨迹与多轮迭代

在启动 Uvicorn 的后端终端中查看 `agent trace=...` 日志。每条日志包含请求追踪 ID、会话 ID、耗时、事件和执行摘要，记录规划轮次、工具开始/完成/失败、回答开始和请求结束。默认不记录完整提示词、附件正文或逐字回答；执行摘要可能包含用户问题的简短描述。

`apps/api/.env` 可配置（修改后重启后端）：

```dotenv
AGENT_MAX_ITERATIONS=12
AGENT_TRACE_ENABLED=true
```

迭代上限范围为 1–50，默认 12。每轮把所有工具调用结果交回模型，由模型决定继续调用还是回答；工具执行失败也会反馈给模型，允许它调整策略。达到上限后基于已有结果生成回答，并要求说明未完成的核验。`agent.limit_reached` 表示触及上限，`tool.failed` 表示工具失败。关闭日志可设置 `AGENT_TRACE_ENABLED=false`。

真实的模型自主迭代需要 `DEMO_MODE=false` 和有效的 `DEEPSEEK_API_KEY`；演示模式不会自主规划多轮工具调用。联网工具还需要配置 `TAVILY_API_KEY`。这些日志展示可观察的执行状态与摘要。

## 文档生成检查与修订

Word 导出使用 Markdown 语法树，按原始顺序生成多个表格、标题、加粗、斜体、链接、引用和独立编号列表。页面使用 A4，表格按内容分配宽度、跨页重复表头，并提供页码。

普通对话生成 Word 时，会先生成草稿，再检查导出结构，并使用模型审阅已有资料与文档是否一致。需要修改时重新生成并检查，默认最多修订两次。此过程只修订下载文件的正文，聊天中的原始回答保留；Excel 同时导出时使用相同的最终正文。审阅失败或返回不完整内容时保留最近一版完整草稿，检查状态与未解决问题会记录到执行轨迹和消息的 `generated_artifacts[].quality`，不会误报全部通过。

```dotenv
DOCUMENT_REVIEW_ENABLED=true
DOCUMENT_REVIEW_MAX_REVISIONS=2
DOCUMENT_RENDER_ENABLED=true
DOCUMENT_RENDER_TIMEOUT_SECONDS=45
# 可选：LibreOffice soffice 的绝对路径；未填写时从 PATH 查找
DOCUMENT_RENDERER_PATH=
```

真实内容审阅需要启用 DeepSeek。修订会增加模型调用与响应时间；将修订次数设置为 0 时仍进行一次审阅但不改写。关闭 `DOCUMENT_REVIEW_ENABLED` 只跳过模型审阅，保留结构与可用的渲染检查。

自动分页检查需要在后端运行环境安装 LibreOffice（Windows 可将 `DOCUMENT_RENDERER_PATH` 指向 `soffice.exe`）。检查在独立临时目录中将 Word 转为 PDF，检查空白页与文字边界，结束后自动清理。没有渲染器时仍可下载文件，但会明确标记渲染不可用；PDF 检查不等于人工或视觉模型审阅，也不能证明所有事实正确。已有附件的定点编辑与图片生成分支沿用原处理流程，不进入新建文档的内容改写步骤。

## 网页正文工具

新增 `web.fetch`：模型可在搜索后读取公开网页正文，核对日期、地点、原文等细节。使用相同的 `TAVILY_API_KEY`，通过 Tavily Extract 服务提取正文，不在本机直接访问用户提供的地址。正文设有长度上限，截断会明确标注，返回内容按不可信外部资料提供给模型。

未配置联网服务时，只隐藏 `web.search` 和 `web.fetch`；本地简历、招聘检索继续可供模型调用。本次增加的是内置网页工具，并未新增通用 MCP 客户端。

## 对话任务计划

聊天中的执行轨迹按实际调用展示工具名、搜索词、网页地址和结果数量。`execution.update_plan` 展示创建的步骤数、刚完成和开始的具体步骤，不再逐轮重复固定计划文案；旧记录中的连续重复文案合并显示，不补造未保存的调用详情。工具失败仍保留查询对象与错误原因，完整参数和响应继续在控制台查看。

聊天输入框中的“任务计划”开关开启后，普通文本任务会先调用 `execution.update_plan` 拆解任务；关闭时由模型判断复杂任务是否需要计划。此能力需要启用真实 DeepSeek，附件定点编辑与图片生成仍走原有专用流程。

计划包含待处理、进行中、已完成和受阻步骤，完成或受阻必须提供结果摘要或原因。同一时刻最多一个步骤进行中。首次创建后步骤 ID、标题、顺序和数量固定，后续 `execution.update_plan` 按 ID 合并更新，未提交的步骤与结果不会消失；未知 ID、重复 ID 和隐式改名会返回可纠正的参数错误。

模型需要用户决定、补充信息或调整约束时，调用 `execution.ask_user`。后端先将上下文、完整计划、产出、来源、原始任务、附件引用、用户决定和待答问题保存到现有数据库消息元数据，再发送 `execution.interrupted`。前端弹窗同时提供选项和自由输入框，支持稍后处理、提交并继续、结束任务。刷新后从 `execution_interrupt` 恢复待答问题，原始执行状态不会公开到浏览器。

恢复请求仍使用消息流接口，传 `resume_checkpoint_id`、`resume_action`（`continue` 或 `cancel`）及正文中的用户答复。服务端校验会话归属并锁定检查点，已恢复或已结束的检查点返回 409，恢复后沿用原计划和执行上下文；等待答复之后的同批工具不执行。检查点复用现有 SQL 数据库持久化，无需新增数据库迁移或引入 LangGraph 运行时。

全部步骤标记完成后，仍须通过任务验收才能显示“验收通过”。验收包含明确周容量与最低投入的数值检查、方案显式周投入检查，以及独立模型对实际正文的交付数量、范围、日程加总、用户约束和待确认事项的审阅。存在冲突或未决选择会暂停并询问用户，验收失败或不可用不会判为完成。计划任务先保存草稿，界面显示生成、校验或修订阶段，通过验收后才交付完整正文；暂停时草稿可折叠查看，旧记录未经过验收时同样显示未定稿。

计算、表格、排期和交付遗漏由助手自动修订并重新验收，默认最多六次（`TASK_ACCEPTANCE_MAX_REVISIONS=6`，可配置为0至12）。普通排期、任务排序和可合理推定的偏好自行安排。修订草稿保存在服务端，不在聊天中反复输出；`execution.phase` 提供阶段进度。只有原始约束本身冲突或必要信息无法合理推定才询问用户，模型必须提供原始要求中的依据；草稿自己的错误不算用户问题。达到修订上限仍不合格时保存草稿、报告本次交付失败，不弹窗询问是否继续修正，也不判为完成。旧版“是否继续自动调整”检查点会自动恢复一次，不再弹出决策框。原始检查报告保留在控制台与检查点，确需用户决定时弹窗列出最多两条具体问题、简短原因、推荐方案及可选输入框。计划正文默认输出上限为8000 tokens（`TASK_COMPLETION_MAX_TOKENS`）；上游报告`finish_reason=length`时最多自动从断点续写两次，仍不完整则保存断点。

计划仍有待办时会自动推进。模型某轮只产出分析而未调用工具时，会保留实际产出并要求更新计划，随后继续下一步骤；连续多轮没有进度会明确提示受阻，避免空转。工具规划发生可重试的连接错误时最多自动重试两次。不可重试的错误、全部剩余步骤受阻、轮数上限或用户停止仍会结束当前请求，并保存具体原因。

“继续执行剩余步骤”会发送新的对话请求，模型参考此前计划与结果恢复执行；关闭页面后不会由后台继续执行。计划任务按步骤数扩大执行轮数（至少原 `AGENT_MAX_ITERATIONS`，最多 50 轮），达到上限会显示暂停原因并汇总现有结果，未完成步骤保持待继续。最终步骤进度由模型报告，不能代替人工验收，也不会增加项目尚不支持的工具或文件格式。

`CHAT_HISTORY_TOKEN_BUDGET` 控制请求前的历史对话整理；`AGENT_CONTEXT_TOKEN_BUDGET`（默认 24000）控制执行中的输入预算，统计系统提示、当前任务、工具定义、工具参数与工具结果。每次工具规划及最终回答前都会检查，超过预算的 80% 时整理较早的工具交换，保留原始请求、最新计划、结果摘要和来源；工具调用与响应成组保留，避免协议不匹配。原始任务与摘要自身已超出预算时会明确报错。Token 为估算值，输出空间另由 `CHAT_COMPLETION_MAX_TOKENS` 控制。

聊天顶部执行期间显示“执行上下文”，结束后显示“历史上下文”，避免将历史数据库的占用误认为本轮模型实际输入。控制台会记录每次整理前后的 Token 数及自动重试原因。计划摘要与步骤产出仍保存在模型上下文及元数据中，消息正文只显示用户可读的回答。
