"""User-facing descriptions derived from actual tool calls and validated progress."""

from urllib.parse import urlsplit, urlunsplit

from app.core.diagnostics import safe_debug
from app.modules.chat.execution_plan import ExecutionPlan


def brief(value: object, limit: int = 100) -> str:
    text = " ".join(str(safe_debug(value)).split())
    return text[:limit] + ("…" if len(text) > limit else "")


def public_url(value: object) -> str:
    raw = str(value)
    try:
        parts = urlsplit(raw)
        raw = urlunsplit(
            (parts.scheme, parts.netloc.rsplit("@", 1)[-1], parts.path, parts.query, "")
        )
    except ValueError:
        raw = "无法解析的网页地址"
    return brief(raw, 120)


def tool_started_detail(name: str, arguments: dict) -> str:
    if name in {"web.search", "recruitment.search", "resume.search"}:
        return f"调用 {name}：检索「{brief(arguments.get('query', ''))}」。"
    if name == "web.fetch":
        return f"调用 web.fetch：读取 {public_url(arguments.get('url', ''))}。"
    if name == "execution.update_plan":
        return "调用 execution.update_plan：核对并更新步骤状态。"
    if name == "execution.ask_user":
        return f"调用 execution.ask_user：确认「{brief(arguments.get('question', ''), 80)}」。"
    if name == "calendar.create_event_draft":
        return f"调用 {name}：创建「{brief(arguments.get('title', ''))}」日历草稿。"
    return f"调用 {name}。"


def tool_completed_detail(name: str, arguments: dict, result: dict) -> str:
    if name in {"web.search", "recruitment.search", "resume.search"}:
        unit = {
            "web.search": "条来源",
            "recruitment.search": "个职位",
            "resume.search": "段简历原文",
        }[name]
        return (
            f"{name}：检索「{brief(arguments.get('query', ''))}」，"
            f"返回 {len(result.get('results', []))} {unit}。"
        )
    if name == "web.fetch":
        truncated = "，正文已截取" if result.get("truncated") else ""
        return (
            f"web.fetch：已读取「{brief(result.get('title') or '网页正文', 50)}」"
            f"（{public_url(arguments.get('url', ''))}）"
            f"，获得 {len(str(result.get('content') or ''))} 字正文{truncated}。"
        )
    if name == "calendar.create_event_draft":
        return f"{name}：已创建「{brief(result.get('title', ''))}」草稿，尚未写入日历。"
    return f"{name}：执行完成。"


def tool_failed_detail(name: str, arguments: dict, message: str, code: str) -> str:
    action = tool_started_detail(name, arguments).removeprefix("调用 ").removesuffix("。")
    return f"{action}；失败：{brief(message, 80)}（{code}）。"


def plan_update_detail(before: ExecutionPlan | None, after: ExecutionPlan) -> str:
    completed = sum(task.status == "completed" for task in after.tasks)
    active = next((task for task in after.tasks if task.status == "running"), None)
    if before is None:
        return (
            f"execution.update_plan：已创建 {len(after.tasks)} 项任务"
            + (f"；当前：{brief(active.title, 60)}" if active else "")
            + "。"
        )
    previous = {task.id: task for task in before.tasks}
    changes = []
    for task in after.tasks:
        old = previous.get(task.id)
        if old and old.status == task.status:
            if old.result != task.result:
                changes.append(f"补充「{brief(task.title, 60)}」结果")
            continue
        label = {"completed": "完成", "running": "开始", "blocked": "受阻", "pending": "待处理"}[
            task.status
        ]
        changes.append(f"{label}「{brief(task.title, 60)}」")
    if not changes:
        changes = [f"继续「{brief(active.title, 60)}」"] if active else ["已核对各步骤状态"]
    description = "；".join(changes[:3])
    if len(changes) > 3:
        description += f"；另更新 {len(changes) - 3} 项"
    if completed == len(after.tasks):
        description += "；等待验收"
    return f"execution.update_plan：{description}（{completed}/{len(after.tasks)} 步骤完成）。"
