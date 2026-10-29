from __future__ import annotations

import json
import re
from hashlib import sha256
from urllib.parse import urlparse

from lxml import html

from app.modules.recruitment.schemas import JobImportItem

_EDUCATION = re.compile(r"(初中及以下|中专/中技|高中|大专|本科|硕士|博士|学历不限)")
_EXPERIENCE = re.compile(r"(经验不限|应届生|在校生|\d+\s*[-–—至]\s*\d+年|\d+年以上|\d+年以内)")
_SCHEDULE = re.compile(
    r"(双休|大小周|单休|周末双休|朝九晚[五六]|弹性工作|不加班|偶尔加班|"
    r"(?:[01]?\d|2[0-3])[:：]\d{2}\s*[-–—至到]\s*(?:[01]?\d|2[0-3])[:：]\d{2})"
)
_BENEFIT_WORDS = (
    "五险一金",
    "六险一金",
    "补充医疗保险",
    "年终奖",
    "带薪年假",
    "员工旅游",
    "节日福利",
    "零食下午茶",
    "餐补",
    "交通补助",
    "通讯补贴",
    "住房补贴",
    "定期体检",
    "股票期权",
    "包吃",
    "包住",
    "加班补助",
    "全勤奖",
)


class BossPageError(ValueError):
    pass


def _text(node, xpath: str) -> str:
    values = node.xpath(xpath)
    return " ".join(str(value).strip() for value in values if str(value).strip())


def _first(*values: object) -> str:
    for value in values:
        if value is not None and str(value).strip():
            return re.sub(r"\s+", " ", str(value)).strip()
    return ""


def _list(value: object) -> list[str]:
    if isinstance(value, str):
        return [item.strip() for item in re.split(r"[,，、|]", value) if item.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _salary(text: str) -> tuple[int | None, int | None, int | None]:
    match = re.search(r"(\d+(?:\.\d+)?)\s*[-–—]\s*(\d+(?:\.\d+)?)\s*[kK]", text)
    months = re.search(r"(\d{1,2})薪", text)
    if not match:
        return None, None, int(months.group(1)) if months else None
    return (
        int(float(match.group(1)) * 1000),
        int(float(match.group(2)) * 1000),
        int(months.group(1)) if months else None,
    )


def _external_id(url: str, data: dict) -> str:
    for key in ("identifier", "jobId", "job_id", "@id"):
        value = data.get(key)
        if isinstance(value, dict):
            value = value.get("value") or value.get("name")
        if value:
            return str(value)[-160:]
    slug = urlparse(url).path.rstrip("/").split("/")[-1].removesuffix(".html")
    return (slug or sha256(url.encode()).hexdigest())[-160:]


def _job_json_ld(tree) -> dict:
    for raw in tree.xpath('//script[@type="application/ld+json"]/text()'):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            continue
        records = parsed if isinstance(parsed, list) else [parsed]
        for record in records:
            if isinstance(record, dict) and record.get("@type") == "JobPosting":
                return record
    return {}


def parse_boss_job_page(page_html: str, url: str) -> JobImportItem:
    normalized = re.sub(r"\s+", " ", page_html).lower()
    if any(
        marker in normalized for marker in ("加载中，请稍候", "安全验证", "访问过于频繁", "captcha")
    ):
        raise BossPageError("页面触发访问校验，采集已停止")
    tree = html.fromstring(page_html)
    data = _job_json_ld(tree)
    title = _first(
        data.get("title"),
        _text(tree, '//h1[contains(@class,"name")]/text()'),
        _text(tree, '//*[contains(@class,"job-name")]/text()'),
    )
    if not title:
        raise BossPageError("页面中未找到职位标题，可能不是公开职位详情页")
    hiring = (
        data.get("hiringOrganization") if isinstance(data.get("hiringOrganization"), dict) else {}
    )
    address = data.get("jobLocation", {})
    if isinstance(address, list):
        address = address[0] if address else {}
    address = address.get("address", {}) if isinstance(address, dict) else {}
    if not isinstance(address, dict):
        address = {}
    description = _first(
        data.get("description"),
        _text(tree, '//*[contains(@class,"job-sec-text")]//text()'),
        _text(tree, '//*[contains(@class,"job-detail-body")]//text()'),
    )
    description = re.sub(r"<[^>]+>", " ", description)
    description = re.sub(r"\s+", " ", description).strip()
    tag_values = tree.xpath(
        '//*[contains(@class,"job-tags") or contains(@class,"tag-list")]'
        "//*[self::span or self::li]/text()"
    )
    tags = list(dict.fromkeys(str(value).strip() for value in tag_values if str(value).strip()))
    page_text = " ".join(tree.xpath("//body//text()"))
    education = _first(data.get("educationRequirements"), (_EDUCATION.search(page_text) or [""])[0])
    experience = _first(
        data.get("experienceRequirements"), (_EXPERIENCE.search(page_text) or [""])[0]
    )
    salary_text = _first(
        _text(tree, '//*[contains(@class,"salary")]/text()'),
        data.get("baseSalary", {}).get("value", {}).get("value")
        if isinstance(data.get("baseSalary"), dict)
        else "",
    )
    salary_min, salary_max, salary_months = _salary(salary_text)
    benefits = list(
        dict.fromkeys(
            [value for value in tags if value in _BENEFIT_WORDS]
            + [word for word in _BENEFIT_WORDS if word in description]
            + _list(data.get("jobBenefits"))
        )
    )
    schedules = list(
        dict.fromkeys(match.group(1) for match in _SCHEDULE.finditer(description + " " + page_text))
    )
    requirements = description
    return JobImportItem(
        external_id=_external_id(url, data),
        source_url=url,
        title=title,
        company=_first(
            hiring.get("name"), _text(tree, '//*[contains(@class,"company-info")]//a/text()')
        ),
        city=_first(address.get("addressLocality")),
        district=_first(address.get("streetAddress")),
        education=education,
        experience=experience,
        salary_text=salary_text,
        salary_min=salary_min,
        salary_max=salary_max,
        salary_months=salary_months,
        requirements=requirements,
        benefits=benefits,
        work_schedule="、".join(schedules),
        description=description,
        tags=tags,
        raw_json={"json_ld": data},
    )
