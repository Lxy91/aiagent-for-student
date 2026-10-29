from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.modules.recruitment.public_sources import iter_public_jobs


def main() -> int:
    parser = argparse.ArgumentParser(description="导出已核验来源的公开招聘种子数据")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    jobs = iter_public_jobs()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as output:
        for job in jobs:
            output.write(json.dumps(job.model_dump(mode="json"), ensure_ascii=False) + "\n")
    print(f"已导出 {len(jobs)} 条公开招聘记录：{args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
