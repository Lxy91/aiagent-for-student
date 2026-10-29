"""Request-scoped execution plans shared by the model, stream and saved messages."""

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ExecutionTask(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=160)
    status: Literal["pending", "running", "completed", "blocked"] = "pending"
    result: str = Field(default="", max_length=1200)


class ExecutionPlan(BaseModel):
    tasks: list[ExecutionTask] = Field(min_length=1, max_length=12)
    explanation: str = Field(default="", max_length=500)
    status: Literal["running", "completed", "paused", "waiting_user", "cancelled"] = "running"
    acceptance_status: Literal["pending", "passed", "needs_input", "failed"] = "pending"
    acceptance_issues: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_tasks(self) -> "ExecutionPlan":
        if len({task.id for task in self.tasks}) != len(self.tasks):
            raise ValueError("步骤 ID 不能重复")
        if sum(task.status == "running" for task in self.tasks) > 1:
            raise ValueError("同一时间只能有一个进行中的步骤")
        if any(
            task.status in {"completed", "blocked"} and not task.result.strip()
            for task in self.tasks
        ):
            raise ValueError("完成或受阻的步骤必须填写结果或原因")
        return self

    def snapshot(self, *, paused: bool = False) -> dict:
        data = self.model_dump()
        done = (
            all(task.status == "completed" for task in self.tasks)
            and self.acceptance_status == "passed"
        )
        data["status"] = (
            self.status
            if self.status in {"waiting_user", "cancelled"}
            else "completed"
            if done
            else "paused"
            if paused
            else "running"
        )
        return data


class TaskPatch(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    title: str | None = Field(default=None, min_length=1, max_length=160)
    status: Literal["pending", "running", "completed", "blocked"] | None = None
    result: str | None = Field(default=None, max_length=1200)


class PlanUpdate(BaseModel):
    tasks: list[TaskPatch] = Field(min_length=1, max_length=12)
    explanation: str = Field(default="", max_length=500)


def merge_plan(current: ExecutionPlan | None, arguments: dict) -> ExecutionPlan:
    update = PlanUpdate.model_validate(arguments)
    ids = [task.id for task in update.tasks]
    if len(set(ids)) != len(ids):
        raise ValueError("步骤 ID 不能重复")
    if current is None:
        return ExecutionPlan.model_validate(
            {
                "tasks": [item.model_dump(exclude_none=True) for item in update.tasks],
                "explanation": update.explanation,
            }
        )
    known = {task.id: task for task in current.tasks}
    if set(ids) - set(known):
        raise ValueError("不能隐式增加或替换原计划步骤；本次只允许按已有步骤 ID 更新进度")
    patches = {task.id: task for task in update.tasks}
    tasks = []
    for task in current.tasks:
        patch = patches.get(task.id)
        if patch and patch.title is not None and patch.title != task.title:
            raise ValueError(f"步骤 {task.id} 的标题已固定，请仅更新状态和结果")
        tasks.append(
            {**task.model_dump(), **(patch.model_dump(exclude_none=True) if patch else {})}
        )
    return ExecutionPlan.model_validate(
        {"tasks": tasks, "explanation": update.explanation or current.explanation}
    )


PLAN_INSTRUCTION = (
    "\n复杂的多目标任务先调用 execution.update_plan 拆成 3–8 个可验收步骤，"
    "简单问答不需要计划。执行时一次只推进一个步骤，完成后调用该工具更新完整计划，"
    "在 result 中保存简洁结果、来源或阻塞原因，以便后续步骤接着执行。"
    "首次创建完整计划后，步骤 ID、标题和顺序固定；"
    "后续仅提交发生变化的步骤，服务端合并，未提交步骤保留。"
    "需要用户选择、补充信息或放宽约束时，必须调用 execution.ask_user 暂停并等待回答，"
    "不得只在正文写‘待确认’，不得擅自放宽用户约束。任务完成还须通过独立验收。"
    "算术、排期、表格遗漏等自身错误先自动修订，不要向用户罗列内部检查报告。"
    "普通时间安排、任务排序和可合理推定的偏好由你自行决定，保留原始硬约束。"
    "不得询问用户是否允许你修正自身错误，或是否继续自动调整。"
    "确需用户决定时只问一个简短问题，给2至3个清楚选项和一句建议。"
    "计划起点遵循用户指定的日期，不得因为系统当前日期不同就自动平移整个计划。"
    "计划更新本身不代表执行成功；不得把工具失败或不支持的文件格式标成完成。"
    "纯分析步骤也要实际完成内容才能标记完成。最终回答前更新计划，"
    "计划中存在 pending 或 running 步骤时，应自动继续执行，不能仅说明下一步后就结束。"
    "每个分析步骤先形成实际产出，再通过工具更新进度；确实缺少用户信息或工具能力时标记 blocked。"
    "明确尚未完成的步骤。execution.update_plan 只记录进度，不生成文件或执行外部操作。"
)


def plan_tool_schema() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "execution__update_plan",
            "description": "创建或更新本次复杂任务的执行计划。提交完整步骤及真实进度。",
            "parameters": PlanUpdate.model_json_schema(),
        },
    }
