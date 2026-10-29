import asyncio

import pytest

from app.core.config import Settings
from app.core.errors import AppError
from app.infrastructure.llm.deepseek import DeepSeekProvider
from app.modules.memory.resume_summary import format_summary, summarize_resume, supported_facts


@pytest.mark.parametrize(
    "source,category,fact,evidence",
    [
        (
            "东海大学 会计学（注册会计师方向）｜学士",
            "education",
            "东海大学会计学学士",
            "东海大学 会计学(注册会计师方向)|学士",
        ),
        (
            "2021.09–2025.06\nMSc Economics",
            "education",
            "MSc Economics，2021.09-2025.06",
            "2021.09-2025.06 MSc Economics",
        ),
        (
            "专业能力：门店运营、库存管理、客户维护",
            "skills",
            "门店运营、库存管理",
            "门店运营、库存管理",
        ),
        ("Research: Protein folding, Python", "projects", "Protein folding", "Protein folding"),
    ],
)
def test_evidence_matches_layout_and_typographic_variations(source, category, fact, evidence):
    accepted, errors = supported_facts({category: [{"text": fact, "evidence": [evidence]}]}, source)
    assert accepted[category] == [fact]
    assert not errors


def test_one_bad_fact_does_not_discard_good_facts():
    accepted, errors = supported_facts(
        {
            "education": [{"text": "东海大学会计学", "evidence": ["东海大学会计学"]}],
            "employment": [{"text": "虚构公司", "evidence": ["根本不存在"]}],
        },
        "东海大学会计学",
    )
    assert accepted["education"] == ["东海大学会计学"]
    assert not accepted.get("employment")
    assert errors


def test_summary_repairs_invalid_evidence(monkeypatch):
    calls = []

    async def complete(self, messages, **kwargs):
        calls.append(list(messages))
        if len(calls) == 1:
            return {"education": [{"text": "东海大学会计学", "evidence": ["错误引用"]}]}
        return {"education": [{"text": "东海大学会计学", "evidence": ["东海大学会计学"]}]}

    monkeypatch.setattr(DeepSeekProvider, "complete_json", complete)
    monkeypatch.setattr(Settings, "deepseek_enabled", property(lambda self: True))
    assert asyncio.run(summarize_resume("东海大学会计学", Settings())) == "教育背景：东海大学会计学"
    assert len(calls) == 2
    assert "evidence" in calls[1][-1]["content"]


def test_partial_summary_survives_failed_repair(monkeypatch):
    calls = []

    async def complete(self, messages, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            raise AppError("MODEL_PROVIDER_ERROR", "连接超时", status_code=502, retryable=True)
        return {"skills": [{"text": "库存管理", "evidence": ["库存管理"]}], "education": None}

    monkeypatch.setattr(DeepSeekProvider, "complete_json", complete)
    monkeypatch.setattr(Settings, "deepseek_enabled", property(lambda self: True))
    assert asyncio.run(summarize_resume("库存管理", Settings())) == "技能：库存管理"


def test_transient_provider_failure_retried_once(monkeypatch):
    calls = []

    async def complete(self, messages, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise AppError("MODEL_PROVIDER_ERROR", "连接超时", status_code=502, retryable=True)
        return {"skills": [{"text": "Excel", "evidence": ["Excel"]}]}

    monkeypatch.setattr(DeepSeekProvider, "complete_json", complete)
    monkeypatch.setattr(Settings, "deepseek_enabled", property(lambda self: True))
    assert asyncio.run(summarize_resume("Excel", Settings())) == "技能：Excel"
    assert len(calls) == 2


def test_overlong_and_many_facts_keep_complete_supported_entries():
    accepted, errors = supported_facts(
        {"skills": [{"text": f"Excel能力{i}", "evidence": ["Excel"]} for i in range(5)]}, "Excel"
    )
    assert not errors and accepted["skills"]
    summary = format_summary(
        {
            category: [f"条目{i}" + "内容" * 40 for i in range(3)]
            for category in [
                "identity",
                "education",
                "employment",
                "skills",
                "projects",
                "certificates",
                "awards",
                "campus",
            ]
        }
    )
    assert len(summary) <= 900
    assert summary.endswith("内容")
