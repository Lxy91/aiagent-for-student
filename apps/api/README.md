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
