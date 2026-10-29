import json

import numpy as np
from fastapi.testclient import TestClient
from qdrant_client import QdrantClient

from app.infrastructure.vector.qdrant import QdrantRecruitmentStore
from app.modules.recruitment.boss_parser import BossPageError, parse_boss_job_page
from app.modules.recruitment.public_sources import iter_public_jobs


def _item() -> dict:
    return {
        "source": "boss",
        "external_id": "abc123",
        "source_url": "https://www.zhipin.com/job_detail/abc123.html",
        "title": "Python 后端工程师",
        "company": "示例科技",
        "city": "北京",
        "district": "海淀区",
        "education": "本科",
        "experience": "1-3年",
        "salary_text": "15-25K·13薪",
        "salary_min": 15000,
        "salary_max": 25000,
        "salary_months": 13,
        "requirements": "熟悉 Python、FastAPI 和 MySQL。",
        "benefits": ["五险一金", "周末双休"],
        "work_schedule": "09:00-18:00、双休",
        "description": "负责后端服务开发，熟悉 Python、FastAPI 和 MySQL。",
        "tags": ["Python", "FastAPI"],
    }


def test_import_update_and_search(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.post(
        "/api/v1/recruitment/jobs/import", json={"items": [_item()]}, headers=auth_headers
    )
    assert response.status_code == 200
    assert response.json()["inserted"] == 1
    assert response.json()["chunks"] >= 1

    unchanged = client.post(
        "/api/v1/recruitment/jobs/import", json={"items": [_item()]}, headers=auth_headers
    )
    assert unchanged.json()["unchanged"] == 1

    results = client.get(
        "/api/v1/recruitment/search", params={"q": "Python 本科 双休"}, headers=auth_headers
    )
    assert results.status_code == 200
    assert results.json()[0]["job"]["title"] == "Python 后端工程师"
    assert results.json()[0]["score"] > 0

    tool_result = client.post(
        "/api/v1/tools/recruitment.search:invoke",
        json={"arguments": {"query": "Python 本科 双休", "max_results": 5}},
        headers=auth_headers,
    )
    assert tool_result.status_code == 200
    assert tool_result.json()["result"]["results"][0]["company"] == "示例科技"


def test_parse_json_ld_job_page() -> None:
    payload = {
        "@type": "JobPosting",
        "identifier": {"value": "boss-001"},
        "title": "数据分析师",
        "hiringOrganization": {"name": "示例数据"},
        "jobLocation": {"address": {"addressLocality": "上海", "streetAddress": "浦东新区"}},
        "educationRequirements": "本科",
        "experienceRequirements": "1-3年",
        "description": "负责数据分析。五险一金，09:00-18:00，周末双休。",
    }
    serialized = json.dumps(payload, ensure_ascii=False)
    page = f'<html><body><script type="application/ld+json">{serialized}</script></body></html>'
    item = parse_boss_job_page(page, "https://www.zhipin.com/job_detail/boss-001.html")
    assert item.title == "数据分析师"
    assert item.city == "上海"
    assert "五险一金" in item.benefits
    assert "周末双休" in item.work_schedule


def test_parser_stops_on_challenge() -> None:
    try:
        parse_boss_job_page("<p>加载中，请稍候</p><iframe></iframe>", "https://www.zhipin.com/")
    except BossPageError as error:
        assert "访问校验" in str(error)
    else:
        raise AssertionError("challenge page must not be parsed")


def test_public_jobs_are_traceable_and_do_not_invent_missing_fields() -> None:
    jobs = iter_public_jobs()
    assert len(jobs) >= 50
    assert len({(job.source_url, job.title) for job in jobs}) == len(jobs)
    assert all(job.source_url.host for job in jobs)
    huawei = next(
        job for job in jobs if job.company.startswith("华为") and job.title == "AI软件工程师"
    )
    assert huawei.salary_text == ""
    assert huawei.work_schedule == ""


class _FakeEmbedder:
    @staticmethod
    def _vector(text: str) -> np.ndarray:
        return np.array([1.0, 0.0] if "Python" in text else [0.0, 1.0])

    def embed(self, texts: list[str]):
        yield from (self._vector(text) for text in texts)

    def query_embed(self, query: str):
        yield self._vector(query)


def test_qdrant_vector_index_round_trip(
    client: TestClient, auth_headers: dict[str, str], monkeypatch
) -> None:
    store = QdrantRecruitmentStore(
        client=QdrantClient(":memory:"),
        embedder=_FakeEmbedder(),
        collection_name="test_jobs",
    )
    monkeypatch.setattr(
        "app.modules.recruitment.api.QdrantRecruitmentStore.from_settings",
        lambda _: store,
    )
    response = client.post(
        "/api/v1/recruitment/jobs/import",
        json={"items": [_item()]},
        headers=auth_headers,
    )
    assert response.status_code == 200
    results = client.get(
        "/api/v1/recruitment/search",
        params={"q": "Python 后端"},
        headers=auth_headers,
    )
    assert results.status_code == 200
    assert results.json()[0]["job"]["title"] == "Python 后端工程师"
    assert store.client.count("test_jobs", exact=True).count == 1
