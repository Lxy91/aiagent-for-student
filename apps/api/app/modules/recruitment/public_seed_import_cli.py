from __future__ import annotations

import asyncio

from app.core.config import get_settings
from app.infrastructure.db.session import engine, session_factory
from app.infrastructure.vector.qdrant import QdrantRecruitmentStore
from app.modules.recruitment.public_sources import iter_public_jobs
from app.modules.recruitment.service import RecruitmentService


async def import_public_jobs() -> None:
    try:
        settings = get_settings()
        vector_store = (
            QdrantRecruitmentStore.from_settings(settings) if settings.qdrant_available else None
        )
        async with session_factory() as session:
            result = await RecruitmentService(session, vector_store).import_jobs(iter_public_jobs())
        print(
            "公开招聘数据导入完成："
            f"新增 {result.inserted}，更新 {result.updated}，"
            f"未变化 {result.unchanged}，生成文本块 {result.chunks}"
        )
    finally:
        await engine.dispose()


def main() -> int:
    asyncio.run(import_public_jobs())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
