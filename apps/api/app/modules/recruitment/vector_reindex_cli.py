from __future__ import annotations

import asyncio

from app.core.config import get_settings
from app.infrastructure.db.session import engine, session_factory
from app.infrastructure.vector.qdrant import QdrantRecruitmentStore
from app.modules.recruitment.service import RecruitmentService


async def rebuild() -> None:
    settings = get_settings()
    if not settings.qdrant_available:
        raise RuntimeError("Qdrant 未启用，请检查 QDRANT_ENABLED 和 QDRANT_URL")
    store = QdrantRecruitmentStore.from_settings(settings)
    try:
        async with session_factory() as session:
            count = await RecruitmentService(session, store).rebuild_vector_index()
        print(f"Qdrant 重建完成：{count} 个职位文本块")
    finally:
        await engine.dispose()


def main() -> int:
    asyncio.run(rebuild())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
