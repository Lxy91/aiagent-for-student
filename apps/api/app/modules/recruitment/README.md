# 招聘信息采集与 RAG 入库

该模块将公开职位信息标准化为可检索记录，并按约 900 字切分为 RAG 文本块。字段包括职位、公司、城市、学历、工作经验、薪资、职位要求、福利、工作时长和标签。

## 合规采集

采集器只访问无需登录的公开页面，读取并遵守 `robots.txt`，同一请求至少间隔 5 秒；遇到登录、验证码、安全验证、403 或 429 会立即停止。它不会接收账号、Cookie，也不包含验证码处理或访问控制规避逻辑。

```powershell
cd apps/api
python -m app.modules.recruitment.cli `
  "https://www.zhipin.com/web/geek/jobs?city=101010100&query=Python" `
  --max-pages 100 `
  --delay 8 `
  --output data/boss-jobs.jsonl
```

如果平台不允许自动访问，可将合法取得的结构化数据转换成 `JobImportItem` 格式，再分批调用 `POST /api/v1/recruitment/jobs/import`，每批最多 500 条。

## 已核验的公开招聘种子数据

`public_sources.py` 收录企业官网及高校就业官网公开发布的招聘公告。每条记录都保留原始网址；页面没有公开的薪资、工时或福利字段保持为空，不进行推测。导出 JSONL：

```powershell
cd apps/api
python -m app.modules.recruitment.public_seed_cli --output data/public-jobs.jsonl
```

执行数据库迁移后，可一键导入当前配置的数据库：

```powershell
alembic upgrade head
python -m app.modules.recruitment.public_seed_import_cli
```

## API

- `POST /api/v1/recruitment/jobs/import`：幂等新增/更新职位并重建文本块。
- `GET /api/v1/recruitment/jobs`：按城市、学历、经验筛选。
- `GET /api/v1/recruitment/search?q=Python 本科 双休`：返回可供 RAG 使用的排序结果与命中摘要。
- `recruitment.search`：注册到智能体工具目录，对话可以直接检索上述职位库。

## Qdrant 向量索引

MySQL 的 `job_postings` 和 `job_chunks` 是事实主库；Qdrant 使用 `job_chunks.id` 作为点 ID，保存本地 FastEmbed 生成的中文向量和过滤元数据。启动本地 Qdrant：

```powershell
docker compose -f compose.qdrant.yml up -d
cd apps/api
python -m app.modules.recruitment.vector_reindex_cli
```

默认模型是 `BAAI/bge-small-zh-v1.5`，首次重建会下载模型。查询优先使用 Qdrant 语义检索；Qdrant 不可用时自动回退到 MySQL 关键词检索。职位新增或内容更新后会尝试同步对应向量；若临时同步失败，运行上述重建命令即可修复。

上线定时任务可以每天运行一次采集器，将 JSONL 按 500 条批量提交到导入接口。生产环境还应配置可识别的联系邮箱、监控 403/429、失败告警和数据保留周期。
