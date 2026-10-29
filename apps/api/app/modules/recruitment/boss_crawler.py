from __future__ import annotations

import asyncio
import json
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
from lxml import html

from app.modules.recruitment.boss_parser import BossPageError, parse_boss_job_page
from app.modules.recruitment.schemas import JobImportItem

USER_AGENT = "WorkplaceAgentRecruitmentBot/0.1 (public-pages-only; contact: project-owner)"


class CrawlPolicyError(RuntimeError):
    pass


@dataclass
class CrawlStats:
    fetched: int = 0
    parsed: int = 0
    skipped: int = 0


class BossPublicCrawler:
    """Conservative crawler for public BOSS pages; never logs in or handles challenges."""

    def __init__(self, *, delay_seconds: float = 8.0, timeout_seconds: float = 20.0) -> None:
        self.delay_seconds = max(5.0, delay_seconds)
        self.client = httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT, "Accept-Language": "zh-CN,zh;q=0.9"},
            timeout=timeout_seconds,
            follow_redirects=True,
        )
        self.stats = CrawlStats()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self.client.aclose()

    async def _robots(self, seed_url: str) -> RobotFileParser:
        parsed = urlparse(seed_url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        response = await self.client.get(robots_url)
        if response.status_code != 200:
            raise CrawlPolicyError(
                f"无法确认 robots.txt（HTTP {response.status_code}），为安全起见停止采集"
            )
        parser = RobotFileParser(robots_url)
        parser.parse(response.text.splitlines())
        return parser

    async def crawl(
        self, seed_urls: list[str], *, max_pages: int = 100
    ) -> AsyncIterator[JobImportItem]:
        if not seed_urls:
            return
        robots = await self._robots(seed_urls[0])
        queue = deque(seed_urls)
        seen: set[str] = set()
        while queue and self.stats.fetched < max_pages:
            url = queue.popleft()
            if url in seen:
                continue
            seen.add(url)
            if urlparse(url).hostname not in {"www.zhipin.com", "zhipin.com"}:
                self.stats.skipped += 1
                continue
            if not robots.can_fetch(USER_AGENT, url):
                raise CrawlPolicyError(f"robots.txt 不允许采集：{url}")
            if self.stats.fetched:
                await asyncio.sleep(self.delay_seconds)
            response = await self.client.get(url)
            self.stats.fetched += 1
            if response.status_code in {401, 403, 429}:
                raise CrawlPolicyError(f"页面返回 HTTP {response.status_code}，采集已停止")
            response.raise_for_status()
            try:
                item = parse_boss_job_page(response.text, str(response.url))
            except BossPageError as error:
                if "访问校验" in str(error):
                    raise CrawlPolicyError(str(error)) from error
                self.stats.skipped += 1
            else:
                self.stats.parsed += 1
                yield item
            tree = html.fromstring(response.text)
            for href in tree.xpath('//a[contains(@href,"/job_detail/")]/@href'):
                discovered = urljoin(str(response.url), href).split("?", 1)[0]
                if discovered not in seen:
                    queue.append(discovered)


async def crawl_to_jsonl(
    seed_urls: list[str], output, *, max_pages: int, delay_seconds: float
) -> CrawlStats:
    async with BossPublicCrawler(delay_seconds=delay_seconds) as crawler:
        async for item in crawler.crawl(seed_urls, max_pages=max_pages):
            output.write(json.dumps(item.model_dump(mode="json"), ensure_ascii=False) + "\n")
        return crawler.stats
