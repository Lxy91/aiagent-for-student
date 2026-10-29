from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from app.modules.recruitment.boss_crawler import CrawlPolicyError, crawl_to_jsonl


def main() -> int:
    parser = argparse.ArgumentParser(description="合规采集 BOSS 公开职位页并导出 JSONL")
    parser.add_argument("urls", nargs="+", help="公开搜索页或职位详情页 URL")
    parser.add_argument("--output", required=True, type=Path, help="JSONL 输出文件")
    parser.add_argument("--max-pages", type=int, default=100)
    parser.add_argument("--delay", type=float, default=8.0, help="请求间隔秒数，最低 5 秒")
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with args.output.open("w", encoding="utf-8") as output:
            stats = asyncio.run(
                crawl_to_jsonl(
                    args.urls,
                    output,
                    max_pages=max(1, min(args.max_pages, 1000)),
                    delay_seconds=args.delay,
                )
            )
    except CrawlPolicyError as error:
        print(f"采集停止：{error}", file=sys.stderr)
        return 2
    print(f"完成：访问 {stats.fetched} 页，解析 {stats.parsed} 条，跳过 {stats.skipped} 页")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
