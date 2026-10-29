import re
from typing import Literal

from pydantic import BaseModel, Field


class UserQuestion(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    reason: str = Field(default="", max_length=2000)
    options: list[str] = Field(default_factory=list, max_length=5)
    recommendation: str = Field(default="", max_length=300)
    problems: list[str] = Field(default_factory=list, max_length=3)


class ExecutionInterrupt(UserQuestion):
    id: str
    requires_input: bool = True
    kind: Literal["question", "error", "acceptance"] = "question"
    status: Literal["waiting", "resolved", "cancelled"] = "waiting"


def issue_summaries(issues: list[str]) -> list[str]:
    result = []
    for issue in issues:
        text = " ".join(str(issue).split())
        if "截断" in text and "关键路径" in text and "状态快照" in text:
            summary = "方案正文被截断，关键路径和状态快照尚未输出。"
        elif "截断" in text:
            summary = "部分正文被截断，方案尚未输出完整。"
        else:
            summary = re.split(r"[。；;\n]", text, maxsplit=1)[0]
            if re.search(r"(.{6,60})\1{2}", summary):
                continue
            summary = summary[:100] + ("…" if len(summary) > 100 else "")
        if (
            summary
            and summary not in result
            and not ("截断" in summary and any("截断" in item for item in result))
        ):
            result.append(summary)
        if len(result) == 2:
            break
    return result


def present_question(data: dict, issues: list[str] | None = None) -> dict:
    """Expose a decision, never a raw audit report (including existing checkpoints)."""
    result = dict(data)
    result["requires_input"] = data.get("requires_input", True)
    if data.get("kind") == "acceptance" and any(
        phrase in str(data.get("question", ""))
        for phrase in (
            "继续自动调整",
            "继续检查并修订",
            "继续修订",
            "从断点继续补完",
            "继续调整方案",
        )
    ):
        result["requires_input"] = False
    problems = issue_summaries(data.get("problems") or issues or [])
    oversized = len(str(data.get("reason", ""))) > 220 or len(str(data.get("question", ""))) > 160
    if oversized and data.get("kind") == "acceptance":
        result.update(
            question="要先保留原来的要求，由我继续调整方案吗？",
            reason="方案还有需要修正的地方，计算和排期问题由我处理。",
            options=["保持原要求，继续自动调整（推荐）", "我来补充优先级"],
            recommendation="建议先保留你的原要求，我会自动修订后重新检查。",
        )
    else:
        result["question"] = str(data.get("question", ""))[:160]
        result["reason"] = (
            "当前进度已保存，确认这一项安排后即可继续。"
            if oversized
            else str(data.get("reason", ""))
        )
        result["options"] = [str(item)[:80] for item in data.get("options", [])[:3]]
        result["recommendation"] = str(data.get("recommendation", ""))[:160]
    result["problems"] = problems
    if data.get("kind") == "acceptance" and any("截断" in item for item in problems):
        result.update(
            question="要从断点继续补完方案吗？",
            reason="草稿已经保存，但还没有写完整。",
            recommendation="建议接着补完缺失章节，保留已经完成的内容。",
            options=["继续补完方案（推荐）", "我来调整输出范围"],
        )
    return result


def ask_user_schema() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "execution__ask_user",
            "description": "仅当原始硬约束互相冲突、必要信息无法合理推定，"
            "或需要改变用户要求时暂停询问。"
            "普通排期、排序、计算和交付遗漏由助手自行处理，不询问是否继续修订。"
            "用户可以选择选项或输入自定义回答；不得自行变更约束。",
            "parameters": UserQuestion.model_json_schema(),
        },
    }
