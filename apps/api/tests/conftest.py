import asyncio
import os
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

os.environ["DEMO_MODE"] = "true"
os.environ["APP_SECRET_KEY"] = "test-secret-key-that-is-long-enough"

from app.infrastructure.db.base import Base  # noqa: E402
from app.infrastructure.db.session import get_session  # noqa: E402
from app.main import app  # noqa: E402

database_path = Path(tempfile.gettempdir()) / "workplace-agent-api-test.sqlite3"
test_engine = create_async_engine(f"sqlite+aiosqlite:///{database_path.as_posix()}")
test_session_factory = async_sessionmaker(test_engine, expire_on_commit=False)


async def override_session() -> AsyncIterator[AsyncSession]:
    async with test_session_factory() as session:
        yield session


async def reset_database() -> None:
    async with test_engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)


@pytest.fixture(autouse=True)
def reset_store() -> None:
    asyncio.run(reset_database())


@pytest.fixture
def client() -> TestClient:
    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def auth_headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "student@example.com",
            "password": "safe-password-123",
            "display_name": "测试同学",
        },
    )
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def pytest_sessionfinish() -> None:
    asyncio.run(test_engine.dispose())
    database_path.unlink(missing_ok=True)
