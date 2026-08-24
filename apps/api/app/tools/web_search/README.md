# web.search

受控联网检索工具。服务端通过 Tavily Search API 查询公开互联网，返回标题、URL、来源域名和摘要。调用上下文中的 `user_id` 与 `trace_id` 只能由服务端注入。

此工具是 `read` 级别，无需用户确认；所有调用均写入 `tool_runs` 审计表。未配置 `TAVILY_API_KEY` 时返回 `TOOL_UNAVAILABLE`，不会使用虚构或缓存结果冒充实时搜索。
